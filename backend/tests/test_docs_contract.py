"""Lightweight contract check: api.md must not drift from the live FastAPI routes
and the Literal status enums defined in schemas.py.

Failures here mean docs/api.md needs to be updated — they are NOT test failures
that indicate a code bug.  Keep this list short and high-signal.
"""
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

API_MD = Path(__file__).parent.parent.parent / "docs" / "api.md"


def api_md_text() -> str:
    return API_MD.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Route coverage
# --------------------------------------------------------------------------- #

def _app_routes() -> list[tuple[str, str]]:
    """Return (METHOD, /path) for every route registered in the FastAPI app."""
    from main import app
    pairs = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                pairs.append((method.upper(), route.path))
    return pairs


# Routes that are internal plumbing, not public API surface.
_UNDOCUMENTED_ALLOWLIST = {
    ("GET",  "/openapi.json"),
    ("HEAD", "/openapi.json"),
    ("GET",  "/docs"),
    ("HEAD", "/docs"),
    ("GET",  "/docs/oauth2-redirect"),
    ("HEAD", "/docs/oauth2-redirect"),
    ("GET",  "/redoc"),
    ("HEAD", "/redoc"),
    ("HEAD", "/"),
    ("HEAD", "/health"),
}


def test_all_routes_mentioned_in_api_md():
    """Every route path must appear somewhere in docs/api.md."""
    text = api_md_text()
    routes = _app_routes()
    missing = []
    for method, path in routes:
        if (method, path) in _UNDOCUMENTED_ALLOWLIST:
            continue
        # HEAD is automatically added by FastAPI for every GET — skip them
        # unless they appear in the allowlist (already handled above).
        if method == "HEAD":
            continue
        if path not in text:
            missing.append(f"{method} {path}")
    assert not missing, (
        "The following routes are not mentioned in docs/api.md:\n"
        + "\n".join(f"  {r}" for r in sorted(missing))
        + "\n\nAdd them to docs/api.md or to _UNDOCUMENTED_ALLOWLIST if internal."
    )


# --------------------------------------------------------------------------- #
# Enum / status value drift
# --------------------------------------------------------------------------- #

def test_manual_test_statuses_in_api_md():
    """ManualStatus Literal values must all appear in docs/api.md."""
    import typing
    from schemas import ManualStatus
    values = list(typing.get_args(ManualStatus))
    text = api_md_text()
    missing = [v for v in values if v not in text]
    assert not missing, (
        f"Manual test status value(s) {missing} are missing from docs/api.md. "
        "Update the 'status values' line in the Manual Tests section."
    )


def test_scan_statuses_in_api_md():
    """ScanStatus Literal values must all appear in docs/api.md."""
    import typing
    from schemas import ScanStatus
    values = list(typing.get_args(ScanStatus))
    text = api_md_text()
    missing = [v for v in values if v not in text]
    assert not missing, (
        f"Scan status value(s) {missing} are missing from docs/api.md. "
        "Update the 'status values' line in the Scans section."
    )


def test_finding_statuses_in_api_md():
    """FindingStatus Literal values must all appear in docs/api.md."""
    import typing
    from schemas import FindingStatus
    values = list(typing.get_args(FindingStatus))
    text = api_md_text()
    missing = [v for v in values if v not in text]
    assert not missing, (
        f"Finding status value(s) {missing} are missing from docs/api.md. "
        "Update the 'status values' line in the Findings section."
    )


# --------------------------------------------------------------------------- #
# Response key shape
# --------------------------------------------------------------------------- #

def test_recon_response_key(client, auth_headers, program_id):
    """GET /programs/{id}/recon must return a 'recon' key, not 'recon_items'."""
    res = client.get(f"/programs/{program_id}/recon", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert "recon" in body, (
        f"Expected response key 'recon' but got keys: {list(body.keys())}. "
        "docs/api.md documents 'recon' — update the router or the docs."
    )
    assert "recon_items" not in body, (
        "Router returned 'recon_items' but docs/api.md documents 'recon'. "
        "One of them is wrong."
    )


def test_stats_endpoint_keys(client, auth_headers, program_id):
    """GET /programs/{id}/stats must return the keys documented in api.md."""
    res = client.get(f"/programs/{program_id}/stats", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    expected_keys = {
        "recon_count", "scans_count", "findings_count", "manual_tests_count",
        "reports_count", "submissions_count",
        "findings_by_severity", "submissions_by_status",
    }
    missing = expected_keys - body.keys()
    assert not missing, (
        f"GET /programs/{{id}}/stats response is missing keys: {missing}. "
        "Update the endpoint or docs/api.md."
    )


def test_program_object_has_services_count(client, auth_headers, program_id):
    """GET /programs must include services_count in each engagement object."""
    res = client.get("/programs", headers=auth_headers)
    assert res.status_code == 200
    programs = res.json().get("programs", [])
    for p in programs:
        assert "services_count" in p, (
            f"Engagement object missing 'services_count'. "
            "Update serialize_engagement or docs/api.md."
        )
