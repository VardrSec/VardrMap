"""dalfox: job type, candidate import, verification signal, dedup, provenance.

dalfox reports XSS *candidates*. Even its top tier ("V") is dalfox asserting
exploitability, not this platform confirming it, so every row lands as
`status="new"` and the scanner's own signal — tier, detection method,
confidence — is preserved rather than collapsed into our severity.

The fixtures mirror dalfox 3.2.x `-f json` output: one document with findings
under "findings" beside a "meta" envelope. The payload carries a per-run marker
class (`dlx…`), which is exactly why dedup cannot key on the payload or the PoC
URL.
"""
import io
import json

import pytest


def _finding(**overrides):
    item = {
        "type": "V",
        "type_description": "Vulnerable - dalfox asserts this input is exploitable; act on it",
        "detection_method": "dom-verification",
        "confidence": "high",
        "inject_type": "inHTML",
        "method": "GET",
        "data": "https://app.example.com/search?q=%3Csvg%20onload%3Dalert%281%29%20class%3Ddlx1ec4110f%3E",
        "param": "q",
        "location": "Query",
        "payload": "<svg onload=alert(1) class=dlx1ec4110f>",
        "evidence": "<svg onload=alert(1) class=dlx1ec4110f>",
        "cwe": "CWE-79",
        "severity": "High",
        "message_id": 606,
        "message_str": "triggered XSS payload",
    }
    item.update(overrides)
    return item


def _document(*findings):
    return json.dumps(
        {"findings": list(findings), "meta": {"dalfox_version": "3.2.4", "findings_count": len(findings)}}
    ).encode()


def _upload(client, headers, program_id, payload: bytes, job_id: str | None = None):
    data = {"tool_type": "dalfox"}
    if job_id:
        data["job_id"] = job_id
    return client.post(
        f"/programs/{program_id}/imports",
        data=data,
        files={"file": ("dalfox.json", io.BytesIO(payload), "application/json")},
        headers=headers,
    )


def _scans(client, headers, program_id):
    rows = client.get(f"/programs/{program_id}/scans", headers=headers).json()
    items = rows["scans"] if isinstance(rows, dict) and "scans" in rows else rows
    return [s for s in items if s["source"] == "dalfox"]


def _create_job(client, program_id, headers, **body):
    return client.post(
        f"/programs/{program_id}/jobs",
        json={"tool_type": "dalfox", "target_source": "recon", **body},
        headers=headers,
    )


# ── job type ────────────────────────────────────────────────────────────────


def test_dalfox_job_accepted(client, program_id, auth_headers):
    res = _create_job(
        client, program_id, auth_headers,
        config={"limit": 50, "worker": 10, "delay": 100, "mining": "true"},
    )
    assert res.status_code == 200
    assert res.json()["tool_type"] == "dalfox"


@pytest.mark.parametrize(
    "config, field",
    [
        ({"worker": 0}, "worker"),
        ({"worker": 101}, "worker"),
        ({"delay": -1}, "delay"),
        ({"delay": 10_001}, "delay"),
        ({"limit": 0}, "limit"),
        ({"timeout": 0}, "timeout"),
        ({"mining": "maybe"}, "mining"),
        ({"payload": "<script>"}, "unknown config keys"),
    ],
)
def test_dalfox_config_rejected_at_queue_time(client, program_id, auth_headers, config, field):
    res = _create_job(client, program_id, auth_headers, config=config)
    assert res.status_code == 400
    assert field in res.json()["detail"]


# ── the verification signal ─────────────────────────────────────────────────


def test_dalfox_import_preserves_tier_detection_and_confidence(client, program_id, auth_headers):
    res = _upload(client, auth_headers, program_id, _document(_finding()))
    assert res.status_code == 200
    (row,) = _scans(client, auth_headers, program_id)
    assert row["type"] == "vulnerable"
    assert row["detection_method"] == "dom-verification"
    assert row["confidence"] == "high"
    assert row["severity"] == "high"
    assert row["cwe"] == "CWE-79"
    assert row["status"] == "new"


def test_even_the_top_tier_is_a_candidate(client, program_id, auth_headers):
    """dalfox asserting exploitability is not this platform confirming it."""
    _upload(client, auth_headers, program_id, _document(_finding(type="V")))
    (row,) = _scans(client, auth_headers, program_id)
    assert row["status"] == "new"


@pytest.mark.parametrize(
    "tier, expected",
    [("V", "vulnerable"), ("R", "reflected"), ("A", "ast"), ("I", "informational"), ("Z", "")],
)
def test_every_dalfox_tier_maps_to_its_own_name(client, program_id, auth_headers, tier, expected):
    _upload(client, auth_headers, program_id, _document(_finding(type=tier, param=f"p{tier}")))
    (row,) = _scans(client, auth_headers, program_id)
    assert row["type"] == expected


def test_a_reflected_candidate_keeps_its_lower_severity(client, program_id, auth_headers):
    """dalfox grades R as Info; nothing here upgrades it."""
    _upload(
        client, auth_headers, program_id,
        _document(_finding(type="R", severity="Info", detection_method="reflection", confidence="low")),
    )
    (row,) = _scans(client, auth_headers, program_id)
    assert (row["type"], row["severity"], row["confidence"]) == ("reflected", "info", "low")


@pytest.mark.parametrize(
    "field, value",
    [("severity", "catastrophic"), ("detection_method", "telepathy"), ("confidence", "certain")],
)
def test_unknown_signal_values_are_not_stored(client, program_id, auth_headers, field, value):
    """A value dalfox does not define must not be invented into our vocabulary."""
    _upload(client, auth_headers, program_id, _document(_finding(**{field: value})))
    (row,) = _scans(client, auth_headers, program_id)
    assert row[field] == ("info" if field == "severity" else "")


def test_response_bodies_are_not_stored(client, program_id, auth_headers):
    """--include-all adds request/response; neither belongs in our record."""
    secret = "SECRET-RESPONSE-BODY"
    _upload(
        client, auth_headers, program_id,
        _document(_finding(request="GET / HTTP/1.1", response=f"HTTP/1.1 200\\n\\n{secret}")),
    )
    (row,) = _scans(client, auth_headers, program_id)
    assert secret not in json.dumps(row)


# ── deduplication ───────────────────────────────────────────────────────────


def test_reimporting_the_same_scan_adds_nothing(client, program_id, auth_headers):
    """A re-scan re-reports what it still finds; the count must not inflate."""
    first = _upload(client, auth_headers, program_id, _document(_finding()))
    assert first.json()["imported_count"] == 1
    second = _upload(client, auth_headers, program_id, _document(_finding()))
    assert second.json()["imported_count"] == 0
    assert len(_scans(client, auth_headers, program_id)) == 1


def test_a_fresh_payload_marker_is_still_the_same_finding(client, program_id, auth_headers):
    """dalfox mints a new marker class per run, so neither payload nor PoC URL can key dedup."""
    _upload(client, auth_headers, program_id, _document(_finding()))
    rerun = _finding(
        data="https://app.example.com/search?q=%3Csvg%20onload%3Dalert%281%29%20class%3Ddlxfeed9999%3E",
        payload="<svg onload=alert(1) class=dlxfeed9999>",
        evidence="<svg onload=alert(1) class=dlxfeed9999>",
    )
    assert _upload(client, auth_headers, program_id, _document(rerun)).json()["imported_count"] == 0
    assert len(_scans(client, auth_headers, program_id)) == 1


def test_duplicates_within_one_upload_are_dropped(client, program_id, auth_headers):
    res = _upload(client, auth_headers, program_id, _document(_finding(), _finding()))
    assert res.json()["imported_count"] == 1
    assert len(_scans(client, auth_headers, program_id)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"param": "other"},
        {"inject_type": "inJS"},
        {"type": "R"},
        {"data": "https://app.example.com/other?q=x"},
    ],
)
def test_a_genuinely_different_match_is_its_own_row(client, program_id, auth_headers, change):
    """Location, context, parameter and tier each distinguish a real finding."""
    _upload(client, auth_headers, program_id, _document(_finding()))
    assert _upload(
        client, auth_headers, program_id, _document(_finding(**change))
    ).json()["imported_count"] == 1
    assert len(_scans(client, auth_headers, program_id)) == 2


def test_a_tier_change_is_recorded_rather_than_merged(client, program_id, auth_headers):
    """Reflected becoming vulnerable is new information, not an update in place."""
    _upload(client, auth_headers, program_id, _document(_finding(type="R", severity="Info")))
    _upload(client, auth_headers, program_id, _document(_finding(type="V", severity="High")))
    tiers = {row["type"] for row in _scans(client, auth_headers, program_id)}
    assert tiers == {"reflected", "vulnerable"}


# ── provenance ──────────────────────────────────────────────────────────────


def _scans_for_job(client, headers, program_id, job_id):
    rows = client.get(f"/programs/{program_id}/scans?job_id={job_id}", headers=headers).json()
    return rows["scans"]


def test_import_links_candidates_to_the_producing_job(client, program_id, auth_headers):
    job_id = _create_job(client, program_id, auth_headers, config={}).json()["id"]
    res = _upload(client, auth_headers, program_id, _document(_finding()), job_id=job_id)
    assert res.status_code == 200
    (row,) = _scans(client, auth_headers, program_id)
    assert row["job_id"] == job_id
    assert [r["id"] for r in _scans_for_job(client, auth_headers, program_id, job_id)] == [row["id"]]


def test_a_later_job_that_sees_a_known_candidate_still_records_it(client, program_id, auth_headers):
    """Dedup must not erase the fact that this run observed the issue too.

    A deduplicated re-scan stores nothing, so its result links are the only
    record that it saw the issue — which is why /scans?job_id= has to include
    observations and not just the rows a job first produced.
    """
    first_job = _create_job(client, program_id, auth_headers, config={}).json()["id"]
    second_job = _create_job(client, program_id, auth_headers, config={}).json()["id"]
    _upload(client, auth_headers, program_id, _document(_finding()), job_id=first_job)
    res = _upload(client, auth_headers, program_id, _document(_finding()), job_id=second_job)
    assert res.json()["imported_count"] == 0  # stored nothing new
    (row,) = _scans(client, auth_headers, program_id)
    # The row keeps its origin, and the second job's observation is still visible.
    assert row["job_id"] == first_job
    assert [r["id"] for r in _scans_for_job(client, auth_headers, program_id, second_job)] == [
        row["id"]
    ]


def test_import_with_another_engagements_job_is_refused(client, program_id, auth_headers):
    res = _upload(client, auth_headers, program_id, _document(_finding()), job_id="made-up")
    assert res.status_code == 404
    assert _scans(client, auth_headers, program_id) == []


# ── scheduled runs ──────────────────────────────────────────────────────────
#
# A schedule queues an ordinary job, so dalfox can recur. These pin what is
# PRESERVED for the scheduled path: execution limits, claim-time warnings and
# stop-work. (That stop-work does not pause a schedule is pinned once, tool-
# agnostically, in the ffuf tests.)

from datetime import datetime, timedelta, timezone  # noqa: E402

from db import get_db  # noqa: E402
from main import app  # noqa: E402
from models import ScheduledScan  # noqa: E402


def _schedule(client, program_id, headers, **body):
    return client.post(
        f"/programs/{program_id}/schedules",
        json={"tool_type": "dalfox", "target_source": "recon", "interval": "hourly", **body},
        headers=headers,
    )


def _make_due(program_id):
    db = next(app.dependency_overrides[get_db]())
    try:
        for s in db.query(ScheduledScan).filter(ScheduledScan.program_id == program_id):
            s.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()


def _pending(client, headers, program_id):
    jobs = client.get("/jobs/pending", headers=headers).json()["jobs"]
    return [j for j in jobs if j["program_id"] == program_id]


def test_dalfox_can_be_scheduled(client, program_id, auth_headers):
    res = _schedule(client, program_id, auth_headers, config={"worker": 5, "delay": 100})
    assert res.status_code in (200, 201), res.text
    assert res.json()["tool_type"] == "dalfox"


@pytest.mark.parametrize(
    "config",
    [
        {"worker": 0},  # concurrency cannot be removed
        {"worker": 101},
        {"delay": -1},
        {"delay": 10_001},
        {"mining": "maybe"},
        {"payload": "<script>"},
    ],
)
def test_a_dalfox_schedule_cannot_carry_what_a_job_could_not(client, program_id, auth_headers, config):
    """Load limits are validated when the schedule is created, exactly as for a job."""
    assert _schedule(client, program_id, auth_headers, config=config).status_code == 400


def test_a_scheduled_dalfox_job_carries_the_schedules_config_unchanged(client, program_id, auth_headers):
    config = {"worker": 5, "delay": 100, "mining": False}
    _schedule(client, program_id, auth_headers, config=config)
    _make_due(program_id)
    (job,) = _pending(client, auth_headers, program_id)
    assert job["tool_type"] == "dalfox" and job["config"] == config


def test_claiming_a_scheduled_dalfox_job_returns_policy_warnings(client, program_id, auth_headers):
    """Policy is met at claim, not when the schedule is created or the job materialized."""
    _schedule(client, program_id, auth_headers, config={"worker": 5})
    _make_due(program_id)
    (job,) = _pending(client, auth_headers, program_id)
    claim = client.post(f"/jobs/{job['id']}/claim", headers=auth_headers)
    assert claim.status_code == 200, claim.text
    assert isinstance(claim.json()["warnings"], list)


def test_stop_work_refuses_the_claim_of_a_scheduled_dalfox_job(client, program_id, auth_headers):
    _schedule(client, program_id, auth_headers, config={"worker": 5})
    _make_due(program_id)
    (job,) = _pending(client, auth_headers, program_id)
    client.post(f"/programs/{program_id}/stop-work", json={"reason": "incident"}, headers=auth_headers)
    claim = client.post(f"/jobs/{job['id']}/claim", headers=auth_headers)
    assert claim.status_code == 403
    assert "stop_work_active" in claim.text