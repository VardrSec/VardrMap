"""Request-rate and custom-header controls on scan jobs, plus the engagement ceiling."""

import pytest


def _job(client, pid, headers, tool, config):
    return client.post(
        f"/programs/{pid}/jobs",
        json={"tool_type": tool, "target_source": "scope", "config": config},
        headers=headers,
    )


@pytest.mark.parametrize("tool", ["httpx", "nuclei", "katana"])
def test_rate_accepted_and_bounded(client, program_id, auth_headers, tool):
    ok = _job(client, program_id, auth_headers, tool, {"rate": 40})
    assert ok.status_code == 200 and ok.json()["config"]["rate"] == 40
    assert _job(client, program_id, auth_headers, tool, {"rate": 0}).status_code == 400
    assert _job(client, program_id, auth_headers, tool, {"rate": 5000}).status_code == 400


@pytest.mark.parametrize("tool", ["httpx", "nuclei", "katana", "ffuf", "dalfox"])
def test_headers_accepted_as_object_and_list(client, program_id, auth_headers, tool):
    obj = _job(client, program_id, auth_headers, tool, {"headers": {"X-Bug-Bounty": "me"}})
    assert obj.status_code == 200
    lst = _job(client, program_id, auth_headers, tool, {"headers": ["X-Bug-Bounty: me"]})
    assert lst.status_code == 200


def test_headers_rejected_for_tools_that_do_not_take_them(client, program_id, auth_headers):
    # subfinder is not a traffic tool; headers is not an allowed key for it.
    res = _job(client, program_id, auth_headers, "subfinder", {"headers": {"X-A": "b"}})
    assert res.status_code == 400


@pytest.mark.parametrize("bad", [
    {"X-Evil": "a\r\nInjected: 1"},   # CRLF injection
    {"X-Evil": "a\nb"},               # bare LF
    {"Bad Name": "v"},                # non-token name
])
def test_header_injection_rejected(client, program_id, auth_headers, bad):
    assert _job(client, program_id, auth_headers, "httpx", {"headers": bad}).status_code == 400


def test_too_many_headers_rejected(client, program_id, auth_headers):
    many = {f"X-H{i}": "v" for i in range(21)}
    assert _job(client, program_id, auth_headers, "httpx", {"headers": many}).status_code == 400


# ── engagement-wide ceiling ──────────────────────────────────────────────────


@pytest.fixture
def capped_engagement(client, auth_headers):
    pid = client.post(
        "/programs", json={"name": "Capped", "max_request_rate": 30}, headers=auth_headers
    ).json()["id"]
    yield pid
    client.delete(f"/programs/{pid}", headers=auth_headers)


def test_ceiling_is_stored_and_returned(client, auth_headers, capped_engagement):
    got = client.get(f"/programs/{capped_engagement}", headers=auth_headers).json()
    assert got["max_request_rate"] == 30


def test_ceiling_rejects_an_explicit_rate_above_it(client, auth_headers, capped_engagement):
    res = _job(client, capped_engagement, auth_headers, "httpx", {"rate": 100})
    assert res.status_code == 400


def test_ceiling_keeps_an_explicit_rate_within_it(client, auth_headers, capped_engagement):
    res = _job(client, capped_engagement, auth_headers, "httpx", {"rate": 20})
    assert res.status_code == 200 and res.json()["config"]["rate"] == 20


def test_ceiling_binds_a_job_with_no_rate(client, auth_headers, capped_engagement):
    # httpx's own default (150) is above the ceiling, so the ceiling is injected.
    res = _job(client, capped_engagement, auth_headers, "httpx", {})
    assert res.status_code == 200 and res.json()["config"]["rate"] == 30


def test_ceiling_can_be_cleared(client, auth_headers, capped_engagement):
    client.patch(
        f"/programs/{capped_engagement}", json={"max_request_rate": None}, headers=auth_headers
    )
    got = client.get(f"/programs/{capped_engagement}", headers=auth_headers).json()
    assert got["max_request_rate"] is None
    # With no ceiling, a job with no rate is left as the tool's own default.
    res = _job(client, capped_engagement, auth_headers, "httpx", {})
    assert res.status_code == 200 and "rate" not in res.json()["config"]
