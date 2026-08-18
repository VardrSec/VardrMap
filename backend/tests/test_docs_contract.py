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


def status_values_line(prefix: str) -> str:
    """Return the single `status` values: line that starts with `prefix`.

    Whole-document substring checks only prove a value appears *somewhere*, which
    is how `accepted` and `rejected` survived in the engagement object long after
    the finding lifecycle dropped them — the words existed elsewhere in the file.
    Pinning one line lets a test assert both directions: every current value is
    listed, and no retired value is.
    """
    matches = [
        line for line in api_md_text().splitlines()
        if line.startswith(prefix) and "`status` values:" in line
    ]
    assert len(matches) == 1, (
        f"Expected exactly one '`status` values:' line starting with {prefix!r} "
        f"in docs/api.md, found {len(matches)}. Adjust the prefix or the doc so "
        f"the contract test pins a single line."
    )
    return matches[0]


def assert_exact_status_values(line: str, literal, label: str) -> None:
    """The documented line must list every enum value and nothing retired."""
    import re
    import typing

    expected = set(typing.get_args(literal))
    # Only the part after "`status` values:" — the same line names other fields.
    tail = line.split("`status` values:", 1)[1]
    documented = set(re.findall(r"`([a-z_]+)`", tail))

    missing = expected - documented
    obsolete = documented - expected
    assert not missing, (
        f"{label}: value(s) {sorted(missing)} are missing from the documented "
        f"status list in docs/api.md.\n  line: {line.strip()}"
    )
    assert not obsolete, (
        f"{label}: docs/api.md still documents retired status value(s) "
        f"{sorted(obsolete)} that the schema no longer accepts. A client "
        f"branching on them would be wrong.\n  line: {line.strip()}"
    )


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
    """Documented finding statuses must match FindingStatus exactly."""
    from schemas import FindingStatus
    assert_exact_status_values(
        status_values_line("`title` is required. `severity` values:"),
        FindingStatus,
        "Findings",
    )


def test_report_statuses_in_api_md():
    """Documented report statuses must match ReportStatus exactly.

    Guards the deliverable lifecycle against a slide back to bounty vocabulary:
    `submitted`/`accepted`/`duplicate`/`informative`/`resolved` reappearing here
    fails as 'retired'.
    """
    from schemas import ReportStatus
    assert_exact_status_values(
        status_values_line("`title` is required. `finding_id` is optional"),
        ReportStatus,
        "Reports",
    )


def test_engagement_object_findings_by_status_uses_current_statuses():
    """The engagement object example must not show retired finding statuses.

    This is the drift that prompted the check: the example kept `accepted` and
    `rejected` long after the lifecycle became new/candidate/triaged/in_progress/
    closed, and a whole-document substring test could not see it.
    """
    import json
    import re
    import typing
    from schemas import FindingStatus

    lines = [
        line for line in api_md_text().splitlines()
        if '"findings_by_status"' in line
    ]
    assert lines, 'No "findings_by_status" example found in docs/api.md.'

    allowed = set(typing.get_args(FindingStatus))
    for line in lines:
        body = re.search(r"\{.*\}", line)
        assert body, f"Could not parse the findings_by_status example: {line.strip()}"
        documented = set(json.loads(body.group(0)).keys())
        obsolete = documented - allowed
        assert not obsolete, (
            f"docs/api.md documents retired finding status(es) {sorted(obsolete)} "
            f"in a findings_by_status example. Current statuses: {sorted(allowed)}."
            f"\n  line: {line.strip()}"
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
        "reports_count", "findings_by_severity",
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


def test_report_object_matches_documented_fields(client, auth_headers, program_id):
    """Every field the report example documents must actually be serialized.

    `created_at` was documented and stored but never returned, so a client
    following the docs got `undefined`. Deriving the expected set from the doc
    example means the two cannot drift apart again.
    """
    import json
    import re

    created = client.post(
        f"/programs/{program_id}/reports",
        json={"title": "Contract check"},
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()

    example = next(
        (line for line in api_md_text().splitlines() if '"reports": [ {' in line),
        None,
    )
    assert example, 'No "reports": [ { ... } ] example found in docs/api.md.'
    documented = set(json.loads(re.search(r"\{.*\}", example).group(0)).keys())

    missing = documented - body.keys()
    assert not missing, (
        f"Report object is missing documented field(s) {sorted(missing)}. "
        f"Either serialize them in serialize_report or correct docs/api.md."
    )
    # Sorted by created_at, so it has to be populated, not merely present.
    assert body["created_at"], "created_at must be populated on a new report."
