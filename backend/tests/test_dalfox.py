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

# ── payload and evidence are not lost ───────────────────────────────────────
#
# Regression for a data-loss bug. The importer ran everything through strip_html,
# which deletes anything tag-shaped and HTML-encodes "&". For an XSS scanner that
# destroys the evidence: the payload `<svg onload=alert(1)>` was stored as nothing,
# and a PoC URL `?a=1&q=x` as `?a=1&amp;q=x`. The prose may be sanitised; the
# payload, evidence and PoC URL must come back exactly as dalfox reported them.

# Verbatim from `dalfox scan -f json` (3.2.4) against a local reflecting fixture.
REAL_FINDING = {
    "confidence": "high",
    "confidence_reason": "payload reached an executable position in the parsed response",
    "cwe": "CWE-79",
    "data": "http://127.0.0.1:42901/?q=%3Csvg%20onload%3Dalert%281%29%20class%3Ddlx939ec0c3%3E",
    "detection_method": "reflection",
    "evidence": "DOM verification successful for param q (DOM marker)",
    "inject_type": "inHTML",
    "location": "Query",
    "message_id": 606,
    "message_str": "Triggered XSS Payload (DOM marker): q=<svg onload=alert(1) class=dlx939ec0c3>",
    "method": "GET",
    "param": "q",
    "payload": "<svg onload=alert(1) class=dlx939ec0c3>",
    "severity": "High",
    "type": "V",
    "type_description": "Vulnerable - dalfox asserts this input is exploitable; act on it",
}


def _import_one(client, program_id, headers, **overrides):
    res = _upload(client, headers, program_id, _document({**REAL_FINDING, **overrides}))
    assert res.status_code == 200, res.text
    return _scans(client, headers, program_id)


def test_the_real_payload_survives_import_exactly(client, program_id, auth_headers):
    (row,) = _import_one(client, program_id, auth_headers)
    assert row["payload"] == "<svg onload=alert(1) class=dlx939ec0c3>"
    assert row["payload"] == REAL_FINDING["payload"]  # not "", which is what strip_html left


def test_the_real_evidence_survives_import_exactly(client, program_id, auth_headers):
    (row,) = _import_one(client, program_id, auth_headers)
    assert row["match_evidence"] == "DOM verification successful for param q (DOM marker)"


@pytest.mark.parametrize(
    "payload",
    [
        '"><img src=x onerror=alert(1)>',
        "<script>alert(1)</script>",
        "javascript:alert(1)//",
        "'-alert(1)-'",
        "a&b<c>\"d'",
        "&lt;already-escaped&gt;",  # must not be decoded or double-encoded
        "<svg/onload=alert`1`>",
    ],
)
def test_hostile_looking_payloads_are_stored_exactly_as_text(client, program_id, auth_headers, payload):
    (row,) = _import_one(client, program_id, auth_headers, payload=payload, evidence=payload)
    assert row["payload"] == payload
    assert row["match_evidence"] == payload


def test_a_poc_url_keeps_its_ampersands(client, program_id, auth_headers):
    """`&` became `&amp;`, so the stored PoC URL was no longer the URL that triggered it."""
    url = "http://127.0.0.1:42901/?a=1&q=%3Csvg%3E&b=2"
    (row,) = _import_one(client, program_id, auth_headers, data=url)
    assert row["asset"] == url and row["matched_at"] == url
    assert "&amp;" not in row["asset"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>1</script>", "not a url", ""])
def test_a_poc_url_that_is_not_http_is_dropped(client, program_id, auth_headers, url):
    (row,) = _import_one(client, program_id, auth_headers, data=url)
    assert row["asset"] == "" and row["matched_at"] == ""


def test_the_description_stays_sanitised_and_does_not_carry_a_mangled_payload(
    client, program_id, auth_headers
):
    """Prose still goes through strip_html. It points at the payload column instead of
    carrying a copy that the sanitiser would turn into a dangling `q=`."""
    (row,) = _import_one(client, program_id, auth_headers)
    assert "<" not in row["description"] and ">" not in row["description"]
    assert "q=[payload]" in row["description"]
    assert "q= " not in row["description"] and not row["description"].endswith("q=")


def test_control_characters_are_removed_and_length_is_bounded(client, program_id, auth_headers):
    (row,) = _import_one(
        client, program_id, auth_headers,
        payload="a\x00b\x07c\x1bd\ne\tf" + "x" * 5000,
        evidence="ok\x00" + "y" * 5000,
    )
    assert row["payload"].startswith("abcd\ne\tf")
    assert not any(c in row["payload"] for c in "\x00\x07\x1b")
    assert len(row["payload"]) <= 2000 and len(row["match_evidence"]) <= 2000


def test_parameter_names_shaped_like_tags_stay_distinct_for_dedup(client, program_id, auth_headers):
    """strip_html would have turned both into "", merging two different parameters."""
    res = _upload(
        client, auth_headers, program_id,
        _document({**REAL_FINDING, "param": "<a>"}, {**REAL_FINDING, "param": "<b>"}),
    )
    assert res.json()["imported_count"] == 2
    assert {r["template_id"] for r in _scans(client, auth_headers, program_id)} == {
        "inHTML:<a>",
        "inHTML:<b>",
    }


def test_two_real_runs_still_dedupe_with_lossless_fields(client, program_id, auth_headers):
    """Preserving the payload must not break dedup: the per-run marker is in the payload."""
    second = {
        **REAL_FINDING,
        "payload": "<svg onload=alert(1) class=dlxd722db8d>",
        "data": REAL_FINDING["data"].replace("dlx939ec0c3", "dlxd722db8d"),
    }
    assert _upload(client, auth_headers, program_id, _document(REAL_FINDING)).json()["imported_count"] == 1
    assert _upload(client, auth_headers, program_id, _document(second)).json()["imported_count"] == 0
    (row,) = _scans(client, auth_headers, program_id)
    assert row["payload"] == REAL_FINDING["payload"], "the first-seen evidence is kept, untouched"


def test_payload_and_evidence_are_returned_by_the_scans_api(client, program_id, auth_headers):
    _import_one(client, program_id, auth_headers)
    body = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"][0]
    assert {"payload", "match_evidence"} <= set(body)