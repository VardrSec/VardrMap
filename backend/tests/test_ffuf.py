"""ffuf: queueable job type, queue-time config validation, and recon import.

The import side already existed (`parse_ffuf` predates this), so what is new here
is that `ffuf` is a tool a job may name, and that its config is checked before a
runner ever claims it. The wordlist rule is the one that matters: a job names a
wordlist, and VardrRunner resolves that name against its own directory. If this
API accepted a path, it could name any file the runner can read for ffuf to read
and replay at a target.
"""
import io
import json

import pytest

# A real `ffuf -of json` report: results under "results", each with input.FUZZ.
FFUF_REPORT = {
    "results": [
        {
            "input": {"FUZZ": "admin"},
            "url": "https://app.example.com/admin",
            "status": 200,
            "length": 1234,
            "words": 90,
            "lines": 40,
            "content-type": "text/html; charset=utf-8",
        },
        {
            "input": {"FUZZ": "backup.bak"},
            "url": "https://app.example.com/backup.bak",
            "status": 403,
            "length": 12,
            "words": 2,
            "lines": 1,
            "content-type": "text/plain",
        },
    ]
}


def _jsonl(rows) -> bytes:
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode()


def _upload_bytes(client, headers, program_id, payload: bytes):
    return client.post(
        f"/programs/{program_id}/imports",
        data={"tool_type": "ffuf"},
        files={"file": ("ffuf.json", io.BytesIO(payload), "application/json")},
        headers=headers,
    )


def _recon(client, headers, program_id):
    rows = client.get(f"/programs/{program_id}/recon", headers=headers).json()["recon"]
    return [r for r in rows if r["source"] == "ffuf"]


def _create_job(client, program_id, headers, **body):
    return client.post(
        f"/programs/{program_id}/jobs",
        json={"target_source": "scope", **body},
        headers=headers,
    )


# ── job type ────────────────────────────────────────────────────────────────


def test_ffuf_job_accepted(client, program_id, auth_headers):
    res = _create_job(
        client, program_id, auth_headers, tool_type="ffuf", target_source="recon",
        config={"wordlist": "api-paths", "extensions": ".php,.bak",
                "match_codes": "200,403", "rate": 25, "limit": 50},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["tool_type"] == "ffuf"
    assert body["config"]["wordlist"] == "api-paths"


def test_ffuf_job_accepted_with_no_config(client, program_id, auth_headers):
    """Every key is optional; VardrRunner applies its own defaults."""
    res = _create_job(client, program_id, auth_headers, tool_type="ffuf", config={})
    assert res.status_code == 200


def test_ffuf_match_codes_accepts_all(client, program_id, auth_headers):
    res = _create_job(
        client, program_id, auth_headers, tool_type="ffuf", config={"match_codes": "all"}
    )
    assert res.status_code == 200


@pytest.mark.parametrize(
    "wordlist",
    [
        "/usr/share/seclists/common.txt",
        "../../etc/passwd",
        "C:/wordlists/common.txt",
        "C:\\wordlists\\common.txt",
        "sub/dir",
        "common.txt",          # the name carries no extension
        "Common",              # lowercase only, matching the runner
        "has space",
        "a" * 41,              # longer than the runner accepts
        "",                    # an explicit empty name is not a name
        "-oN",
    ],
)
def test_ffuf_wordlist_must_be_a_name_not_a_path(client, program_id, auth_headers, wordlist):
    res = _create_job(
        client, program_id, auth_headers, tool_type="ffuf", config={"wordlist": wordlist}
    )
    # An empty string means "unset" everywhere else in this validator, so it is
    # the one value that is tolerated rather than rejected.
    if wordlist == "":
        assert res.status_code == 200
        return
    assert res.status_code == 400
    assert "wordlist" in res.json()["detail"]
    assert "not a path" in res.json()["detail"]


def test_ffuf_wordlist_rejects_a_non_string(client, program_id, auth_headers):
    res = _create_job(
        client, program_id, auth_headers, tool_type="ffuf", config={"wordlist": ["common"]}
    )
    assert res.status_code == 400


@pytest.mark.parametrize(
    "config, field",
    [
        ({"extensions": ".php;id"}, "extensions"),
        ({"extensions": "-oN"}, "extensions"),
        ({"extensions": ".toolongextension"}, "extensions"),
        ({"match_codes": "20x"}, "match_codes"),
        ({"match_codes": "200,everything"}, "match_codes"),
        ({"match_codes": "2000"}, "match_codes"),
        ({"rate": 0}, "rate"),
        ({"rate": 1001}, "rate"),
        ({"rate": "fast"}, "rate"),
        ({"limit": 0}, "limit"),
        ({"timeout": 0}, "timeout"),
    ],
)
def test_ffuf_config_rejected_at_queue_time(client, program_id, auth_headers, config, field):
    res = _create_job(client, program_id, auth_headers, tool_type="ffuf", config=config)
    assert res.status_code == 400
    assert field in res.json()["detail"]


@pytest.mark.parametrize(
    "config, accepted",
    [
        # match_codes takes a bare status code: natural over JSON, and the runner
        # accepts it too.
        ({"match_codes": 200}, True),
        ({"match_codes": [200, 403]}, True),
        ({"match_codes": "200,403"}, True),
        ({"match_codes": True}, False),
        ({"match_codes": 3.5}, False),
        # An extension is never a number, so there is no scalar form to support.
        ({"extensions": ".php"}, True),
        ({"extensions": [".php"]}, True),
        ({"extensions": 3}, False),
        ({"extensions": True}, False),
    ],
)
def test_accepted_types_match_the_runners(client, program_id, auth_headers, config, accepted):
    """This validator and VardrRunner's must agree on which types pass.

    VardrRunner carries the same table in
    `tests/test_ffuf.py::test_accepted_types_match_vardrmaps_validator`. A type
    accepted here and refused there queues a job that clears validation and then
    fails on the operator's machine — the failure mode queue-time validation
    exists to prevent. `{"extensions": 3}` and `{"match_codes": 200}` were each
    on the wrong side of that line before this test existed.
    """
    res = _create_job(client, program_id, auth_headers, tool_type="ffuf", config=config)
    assert res.status_code == (200 if accepted else 400), res.json()


def test_ffuf_rate_cap_cannot_be_disabled(client, program_id, auth_headers):
    """There is no value meaning "unlimited" — the cap bounds load on a client host."""
    for rate in (0, -1, 1_000_000):
        res = _create_job(client, program_id, auth_headers, tool_type="ffuf", config={"rate": rate})
        assert res.status_code == 400, rate
    assert _create_job(
        client, program_id, auth_headers, tool_type="ffuf", config={"rate": 1000}
    ).status_code == 200


def test_ffuf_rejects_unknown_config_keys(client, program_id, auth_headers):
    res = _create_job(
        client, program_id, auth_headers, tool_type="ffuf", config={"url": "https://evil.test"}
    )
    assert res.status_code == 400
    assert "unknown config keys" in res.json()["detail"]


def test_ffuf_accepted_in_a_pipeline_stage(client, program_id, auth_headers):
    res = client.post(
        f"/programs/{program_id}/pipelines",
        json={
            "stages": [
                {"tool_type": "httpx", "target_source": "scope", "config": {}},
                {"tool_type": "ffuf", "target_source": "recon", "config": {"rate": 20}},
            ]
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert [j["tool_type"] for j in res.json()["jobs"]] == ["httpx", "ffuf"]


# ── import ──────────────────────────────────────────────────────────────────


def test_ffuf_report_imports_as_recon(client, program_id, auth_headers):
    res = _upload_bytes(client, auth_headers, program_id, json.dumps(FFUF_REPORT).encode())
    assert res.status_code == 200
    rows = _recon(client, auth_headers, program_id)
    by_path = {r["path"]: r for r in rows}
    assert set(by_path) == {"admin", "backup.bak"}
    assert by_path["admin"]["url"] == "https://app.example.com/admin"
    assert by_path["admin"]["status_code"] == 200
    assert by_path["admin"]["length"] == 1234


def test_ffuf_runner_jsonl_imports_identically(client, program_id, auth_headers):
    """VardrRunner uploads ffuf's own keys as JSONL, so both shapes land the same."""
    res = _upload_bytes(client, auth_headers, program_id, _jsonl(FFUF_REPORT["results"]))
    assert res.status_code == 200
    rows = _recon(client, auth_headers, program_id)
    assert {r["path"] for r in rows} == {"admin", "backup.bak"}


def test_ffuf_import_drops_duplicates_within_one_upload(client, program_id, auth_headers):
    rows = FFUF_REPORT["results"] + FFUF_REPORT["results"]
    res = _upload_bytes(client, auth_headers, program_id, _jsonl(rows))
    assert res.status_code == 200
    assert len(_recon(client, auth_headers, program_id)) == 2


# ── scheduled runs ──────────────────────────────────────────────────────────
#
# A schedule queues an ordinary job, so ffuf can recur. These pin what is
# PRESERVED for the scheduled path (limits, warnings, stop-work) and document the
# one consequence worth knowing: stop-work does not pause a schedule.

from datetime import datetime, timedelta, timezone  # noqa: E402

from db import get_db  # noqa: E402
from main import app  # noqa: E402
from models import ScheduledScan  # noqa: E402


def _schedule(client, program_id, headers, **body):
    return client.post(
        f"/programs/{program_id}/schedules",
        json={"tool_type": "ffuf", "target_source": "recon", "interval": "hourly", **body},
        headers=headers,
    )


def _make_due(program_id):
    """Pretend one interval has elapsed, so the next runner poll materializes the job."""
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


def test_ffuf_can_be_scheduled(client, program_id, auth_headers):
    res = _schedule(client, program_id, auth_headers, config={"wordlist": "common", "rate": 25})
    assert res.status_code in (200, 201), res.text
    assert res.json()["tool_type"] == "ffuf"


@pytest.mark.parametrize(
    "config",
    [
        {"wordlist": "/etc/passwd"},  # a path, not a name
        {"wordlist": "../../x"},
        {"rate": 0},  # the cap cannot be switched off
        {"rate": 1001},
        {"nope": 1},
    ],
)
def test_a_schedule_cannot_carry_what_a_job_could_not(client, program_id, auth_headers, config):
    """Execution limits are validated when the schedule is created, exactly as for a job.

    Otherwise a schedule would be a way round the wordlist-name rule and the rate cap.
    """
    assert _schedule(client, program_id, auth_headers, config=config).status_code == 400


def test_a_scheduled_job_carries_the_schedules_config_unchanged(client, program_id, auth_headers):
    config = {"wordlist": "api-paths", "rate": 25}
    _schedule(client, program_id, auth_headers, config=config)
    _make_due(program_id)
    (job,) = _pending(client, auth_headers, program_id)
    assert job["tool_type"] == "ffuf" and job["config"] == config


def test_claiming_a_scheduled_job_returns_policy_warnings(client, program_id, auth_headers):
    """Authorization, window and scope findings ride back at claim, as for any job.

    Nothing is evaluated when the schedule is created or the job materialized, so the
    claim is the only place a scheduled job meets policy.
    """
    _schedule(client, program_id, auth_headers, config={"rate": 25})
    _make_due(program_id)
    (job,) = _pending(client, auth_headers, program_id)
    claim = client.post(f"/jobs/{job['id']}/claim", headers=auth_headers)
    assert claim.status_code == 200, claim.text
    assert isinstance(claim.json()["warnings"], list)


def test_stop_work_refuses_the_claim_of_a_scheduled_job(client, program_id, auth_headers):
    _schedule(client, program_id, auth_headers, config={"rate": 25})
    _make_due(program_id)
    (job,) = _pending(client, auth_headers, program_id)
    client.post(f"/programs/{program_id}/stop-work", json={"reason": "incident"}, headers=auth_headers)
    claim = client.post(f"/jobs/{job['id']}/claim", headers=auth_headers)
    assert claim.status_code == 403
    assert "stop_work_active" in claim.text


@pytest.mark.parametrize("tool, config", [("ffuf", {"rate": 25}), ("httpx", {"limit": 5})])
def test_stop_work_pauses_a_schedule_so_no_backlog_builds(client, program_id, auth_headers, tool, config):
    """Stop-work stops the schedule, not just the claim.

    Refusing the claim alone left materialization queueing a job per interval behind
    it, all claimable on release -- a burst of repeated active scans the moment work
    resumed. Tool-agnostic: it applies to every scheduled tool.
    """
    _schedule(client, program_id, auth_headers, tool_type=tool, config=config)
    client.post(f"/programs/{program_id}/stop-work", json={"reason": "incident"}, headers=auth_headers)
    for _ in range(4):
        _make_due(program_id)
        _pending(client, auth_headers, program_id)  # the runner's poll
    assert _pending(client, auth_headers, program_id) == []


def test_a_paused_schedule_is_untouched_and_fires_once_on_release(client, program_id, auth_headers):
    """next_run_at is not advanced while stopped, so release yields ONE catch-up job.

    The same rule as after a runner outage: one catch-up job, not one per missed interval.
    """
    _schedule(client, program_id, auth_headers, config={"rate": 25})
    client.post(f"/programs/{program_id}/stop-work", json={"reason": "incident"}, headers=auth_headers)
    for _ in range(4):
        _make_due(program_id)
        _pending(client, auth_headers, program_id)
    schedule = client.get(f"/programs/{program_id}/schedules", headers=auth_headers).json()["schedules"][0]
    assert schedule["enabled"] is True and schedule["last_run_at"] is None

    client.delete(f"/programs/{program_id}/stop-work", headers=auth_headers)
    (job,) = _pending(client, auth_headers, program_id)
    assert job["tool_type"] == "ffuf"
    assert len(_pending(client, auth_headers, program_id)) == 1, "no second job within the interval"
    assert client.post(f"/jobs/{job['id']}/claim", headers=auth_headers).status_code == 200


def test_stop_work_on_one_engagement_leaves_other_schedules_running(client, program_id, auth_headers):
    other = client.post("/programs", json={"name": "Other"}, headers=auth_headers).json()["id"]
    try:
        _schedule(client, program_id, auth_headers, config={"rate": 25})
        _schedule(client, other, auth_headers, config={"rate": 25})
        client.post(f"/programs/{program_id}/stop-work", json={"reason": "incident"}, headers=auth_headers)
        _make_due(program_id)
        _make_due(other)
        assert _pending(client, auth_headers, program_id) == []
        assert len(_pending(client, auth_headers, other)) == 1
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)