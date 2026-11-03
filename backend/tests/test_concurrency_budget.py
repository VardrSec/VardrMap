"""Explicit owned capacity, no scanner or retained database."""
import uuid
import pytest
from datetime import timedelta

from tests.test_execution_control import runner_headers as runner_headers
from tests.conftest import _SessionLocal
from models import Engagement, JobExecution
from execution_control import now


def policy(client, eng, headers, limit=1):
    return client.put(f"/engagements/{eng}/concurrency-policy", headers=headers, json={"limit": limit})


def job(client, eng, headers):
    response = client.post(f"/engagements/{eng}/jobs", headers=headers,
                           json={"tool_type": "httpx", "target_source": "scope"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def claim(client, ident, headers, budget=True):
    binding = {"runner_id": str(uuid.uuid4()), "origin": "http://localhost", "concurrency_budget": budget}
    response = client.post(f"/jobs/{ident}/claim", headers=headers, json=binding)
    return response, binding


def test_capacity_holds_until_owned_confirmed_finish(client, program_id, auth_headers, runner_headers):
    assert policy(client, program_id, runner_headers).status_code == 403
    assert policy(client, program_id, auth_headers).status_code == 200
    first, second = [job(client, program_id, auth_headers) for _ in range(2)]
    assert claim(client, first, runner_headers, False)[0].status_code == 409
    response, binding = claim(client, first, runner_headers)
    assert response.status_code == 200, response.text
    receipt = response.json()["execution_control"]
    assert receipt["capacity_reserved"] is True
    payload = {**binding, "token": receipt["token"]}
    assert claim(client, first, runner_headers)[0].status_code == 409
    assert claim(client, second, runner_headers)[0].status_code == 409
    assert policy(client, program_id, auth_headers, None).status_code == 409
    assert client.delete(f"/jobs/{first}", headers=auth_headers).status_code == 409
    assert client.delete(f"/engagements/{program_id}", headers=auth_headers).status_code == 409
    client.patch(f"/jobs/{first}", headers=auth_headers, json={"status": "failed"})
    assert claim(client, second, runner_headers)[0].status_code == 409
    with _SessionLocal() as db:
        row = db.get(JobExecution, first)
        row.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert claim(client, second, runner_headers)[0].status_code == 409
    for outcome in ["uncertain", "cancelled", "cancelled"]:
        response = client.post(f"/jobs/{first}/execution-finish", headers=runner_headers,
                               json={**payload, "outcome": outcome})
        assert response.status_code == 200, response.text
        if outcome == "uncertain":
            assert claim(client, second, runner_headers)[0].status_code == 409
    response, binding = claim(client, second, runner_headers)
    assert response.status_code == 200
    client.post(f"/jobs/{second}/execution-finish", headers=runner_headers,
                json={**binding, "token": response.json()["execution_control"]["token"], "outcome": "failed"})


def test_enabling_over_legacy_running_refused(client, program_id, auth_headers, runner_headers):
    ident = job(client, program_id, auth_headers)
    assert claim(client, ident, runner_headers, True)[0].status_code == 409
    assert client.post(f"/jobs/{ident}/claim", headers=runner_headers).status_code == 200
    assert policy(client, program_id, auth_headers).status_code == 409


@pytest.mark.parametrize("body", [{}, {"limt": 1}, {"limit": True}, {"limit": "1"}, {"limit": 0}, {"limit": 1001}, {"limit": 1, "disable": True}])
def test_malformed_policy_never_disables_limit(client, program_id, auth_headers, body):
    assert policy(client, program_id, auth_headers).status_code == 200
    response = client.put(f"/engagements/{program_id}/concurrency-policy", headers=auth_headers, json=body)
    assert response.status_code == 422
    with _SessionLocal() as db:
        assert db.get(Engagement, program_id).concurrency_limit == 1


def test_foreign_and_viewer_cannot_configure(client, program_id, auth_headers, other_headers):
    assert policy(client, program_id, other_headers).status_code == 404
    response = client.post(f"/engagements/{program_id}/members", headers=auth_headers,
                           json={"github_id": "gh_user2", "role": "viewer"})
    assert response.status_code == 201
    assert policy(client, program_id, other_headers).status_code == 403
