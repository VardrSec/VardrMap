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
