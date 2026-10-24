"""Agent proposals: inert until a full-access operator approves.

The guardrail under test is that a runner-scoped key (what a compromised agent would hold)
can *create* a proposal but can never *approve* one — only a full-access key applies it.
"""


def _runner_token(client, auth_headers) -> str:
    res = client.post("/auth/apikeys", json={"scope": "runner"}, headers=auth_headers)
    assert res.status_code == 200
    return res.json()["token"]


def _runner_headers(client, auth_headers) -> dict:
    return {"Authorization": f"Bearer {_runner_token(client, auth_headers)}"}


def _propose(client, headers, program_id, **body):
    return client.post(f"/engagements/{program_id}/proposals", json=body, headers=headers)


def _engagement(client, headers, program_id) -> dict:
    return client.get(f"/programs/{program_id}", headers=headers).json()


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #


def test_create_scope_proposal_is_pending_and_keeps_reason_and_source(client, auth_headers, program_id):
    res = _propose(
        client, auth_headers, program_id,
        kind="scope_in",
        payload={"value": "branch.remitly.com", "kind": "domain", "max_severity": "critical"},
        reason="Listed in the HackerOne scope table",
        source="https://hackerone.com/remitly",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "pending"
    assert body["kind"] == "scope_in"
    assert body["reason"] == "Listed in the HackerOne scope table"
    assert body["source"] == "https://hackerone.com/remitly"
    assert body["payload"]["value"] == "branch.remitly.com"
    # Creating it applies nothing.
    assert _engagement(client, auth_headers, program_id)["scope"]["in"] == []


def test_unauthenticated_cannot_propose(client, program_id):
    assert _propose(client, {}, program_id, kind="scope_in", payload={"value": "a.com"}).status_code == 401


def test_other_user_cannot_see_or_propose(client, auth_headers, other_headers, program_id):
    _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "a.com"})
    assert client.get(f"/engagements/{program_id}/proposals", headers=other_headers).status_code == 404
    assert _propose(client, other_headers, program_id, kind="scope_in", payload={"value": "b.com"}).status_code == 404


def test_list_filters_by_status_and_is_newest_first(client, auth_headers, program_id):
    _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "first.com"})
    _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "second.com"})
    rows = client.get(f"/engagements/{program_id}/proposals", headers=auth_headers).json()["proposals"]
    assert [r["payload"]["value"] for r in rows] == ["second.com", "first.com"]
    pending = client.get(f"/engagements/{program_id}/proposals?status=pending", headers=auth_headers).json()
    assert len(pending["proposals"]) == 2
    assert client.get(f"/engagements/{program_id}/proposals?status=approved", headers=auth_headers).json()["proposals"] == []


# --------------------------------------------------------------------------- #
# Bad payloads refused at creation
# --------------------------------------------------------------------------- #


def test_scope_without_a_value_is_refused(client, auth_headers, program_id):
    assert _propose(client, auth_headers, program_id, kind="scope_in", payload={}).status_code == 400


def test_bad_max_severity_is_refused(client, auth_headers, program_id):
    res = _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "a.com", "max_severity": "urgent"})
    assert res.status_code == 400


def test_rate_must_be_an_int_in_range(client, auth_headers, program_id):
    assert _propose(client, auth_headers, program_id, kind="rate_ceiling", payload={"rate": "fast"}).status_code == 400
    assert _propose(client, auth_headers, program_id, kind="rate_ceiling", payload={"rate": 0}).status_code == 400
    assert _propose(client, auth_headers, program_id, kind="rate_ceiling", payload={"rate": 5000}).status_code == 400


def test_authorization_with_a_bad_date_is_refused(client, auth_headers, program_id):
    # Same 422 the real authorizations endpoint returns for an unparseable date.
    res = _propose(client, auth_headers, program_id, kind="authorization", payload={"window_start": "last tuesday"})
    assert res.status_code == 422


def test_too_many_pending_proposals_are_refused(client, auth_headers, program_id, monkeypatch):
    import routers.proposals as proposals

    monkeypatch.setattr(proposals, "_MAX_PENDING", 1)
    assert _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "a.com"}).status_code == 201
    assert _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "b.com"}).status_code == 409


# --------------------------------------------------------------------------- #
# The guardrail: a runner key proposes but cannot approve or reject
# --------------------------------------------------------------------------- #


def test_runner_key_can_propose(client, auth_headers, program_id):
    headers = _runner_headers(client, auth_headers)
    res = _propose(client, headers, program_id, kind="scope_in", payload={"value": "agent.example.com"})
    assert res.status_code == 201


def test_runner_key_cannot_approve_or_reject(client, auth_headers, program_id):
    pid = _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "a.com"}).json()["id"]
    runner = _runner_headers(client, auth_headers)
    assert client.post(f"/engagements/{program_id}/proposals/{pid}/approve", headers=runner).status_code == 403
    assert client.post(f"/engagements/{program_id}/proposals/{pid}/reject", headers=runner).status_code == 403
    # Still pending; nothing applied.
    assert _engagement(client, auth_headers, program_id)["scope"]["in"] == []


# --------------------------------------------------------------------------- #
# Approve applies the change
# --------------------------------------------------------------------------- #


def test_approving_a_scope_proposal_adds_the_scope_item(client, auth_headers, program_id):
    pid = _propose(
        client, auth_headers, program_id,
        kind="scope_in",
        payload={"value": "club.remitly.com", "kind": "domain", "max_severity": "high"},
    ).json()["id"]
    res = client.post(f"/engagements/{program_id}/proposals/{pid}/approve", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    assert res.json()["applied_resource_id"]
    scope_in = _engagement(client, auth_headers, program_id)["scope"]["in"]
    assert [i["value"] for i in scope_in] == ["club.remitly.com"]
    assert scope_in[0]["max_severity"] == "high"


def test_approving_an_authorization_proposal_creates_an_authorization(client, auth_headers, program_id):
    pid = _propose(
        client, auth_headers, program_id,
        kind="authorization",
        payload={"reference": "https://hackerone.com/remitly", "permits": "Rate-limited, non-disruptive testing only"},
    ).json()["id"]
    assert client.post(f"/engagements/{program_id}/proposals/{pid}/approve", headers=auth_headers).status_code == 200
    auths = client.get(f"/engagements/{program_id}/authorizations", headers=auth_headers).json()
    assert any(a["reference"] == "https://hackerone.com/remitly" for a in auths)


def test_approving_a_rate_proposal_sets_the_ceiling(client, auth_headers, program_id):
    pid = _propose(client, auth_headers, program_id, kind="rate_ceiling", payload={"rate": 25}).json()["id"]
    assert client.post(f"/engagements/{program_id}/proposals/{pid}/approve", headers=auth_headers).status_code == 200
    assert _engagement(client, auth_headers, program_id)["max_request_rate"] == 25


def test_rejecting_applies_nothing(client, auth_headers, program_id):
    pid = _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "nope.com"}).json()["id"]
    res = client.post(f"/engagements/{program_id}/proposals/{pid}/reject", headers=auth_headers)
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    assert _engagement(client, auth_headers, program_id)["scope"]["in"] == []


def test_a_resolved_proposal_cannot_be_approved_again(client, auth_headers, program_id):
    pid = _propose(client, auth_headers, program_id, kind="scope_in", payload={"value": "a.com"}).json()["id"]
    assert client.post(f"/engagements/{program_id}/proposals/{pid}/approve", headers=auth_headers).status_code == 200
    again = client.post(f"/engagements/{program_id}/proposals/{pid}/approve", headers=auth_headers)
    assert again.status_code == 409
    assert client.post(f"/engagements/{program_id}/proposals/{pid}/reject", headers=auth_headers).status_code == 409


def test_approve_unknown_proposal_is_404(client, auth_headers, program_id):
    assert client.post(f"/engagements/{program_id}/proposals/does-not-exist/approve", headers=auth_headers).status_code == 404
