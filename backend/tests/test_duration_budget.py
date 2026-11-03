"""Nonrefundable allocation, explicit policy and atomic combination checks."""
import uuid
import pytest
from tests.conftest import _SessionLocal
from tests.test_execution_control import runner_headers as runner_headers
from tests.test_target_budget import queued
from tests.test_vardrgate_jobs import _spec
from models import Engagement, JobExecution
from target_budget import binding


@pytest.fixture(autouse=True)
def disposable_accounting_teardown(program_id):
    yield
    with _SessionLocal() as db:
        row = db.get(Engagement, program_id)
        if row is not None:
            row.duration_allocated = 0
            row.targets_spent = 0
            db.commit()


def policy(client, eng, headers, seconds):
    return client.put(f"/engagements/{eng}/duration-policy", headers=headers, json={"limit_seconds": seconds})


def job(client, eng, headers):
    result = client.post(f"/engagements/{eng}/jobs", headers=headers, json={"tool_type": "httpx", "target_source": "scope"})
    assert result.status_code == 200
    return result.json()["id"]


def claim(client, ident, headers, seconds):
    payload = {"runner_id": str(uuid.uuid4()), "origin": "http://localhost", "duration_seconds": seconds}
    return client.post(f"/jobs/{ident}/claim", headers=headers, json=payload), payload


def test_allocated_seconds_survive_unknown_terminal_delete_and_policy(client, program_id, auth_headers, runner_headers):
    assert policy(client, program_id, auth_headers, 6).status_code == 200
    first, second = [job(client, program_id, auth_headers) for _ in range(2)]
    response, payload = claim(client, first, runner_headers, 3)
    assert response.status_code == 200, response.text
    receipt = response.json()["execution_control"]
    assert receipt["duration_budget"] == {"allocated_seconds": 3, "total_allocated_seconds": 3, "limit_seconds": 6}
    assert claim(client, first, runner_headers, 3)[0].status_code == 409
    assert policy(client, program_id, auth_headers, 9).status_code == 409
    for outcome in ["uncertain", "cancelled", "cancelled"]:
        result = client.post(f"/jobs/{first}/execution-finish", headers=runner_headers,
                             json={**payload, "token": receipt["token"], "outcome": outcome})
        assert result.status_code == 200, result.text
        with _SessionLocal() as db:
            assert db.get(Engagement, program_id).duration_allocated == 3
    assert client.delete(f"/jobs/{first}", headers=auth_headers).status_code == 200
    assert claim(client, second, runner_headers, 4)[0].status_code == 409
    assert policy(client, program_id, auth_headers, None).status_code == 409
    assert policy(client, program_id, auth_headers, 2).status_code == 409
    assert client.delete(f"/engagements/{program_id}", headers=auth_headers).status_code == 409
    assert policy(client, program_id, auth_headers, 9).json()["allocated_seconds"] == 3
    response, payload = claim(client, second, runner_headers, 3)
    assert response.json()["execution_control"]["duration_budget"]["total_allocated_seconds"] == 6
    client.post(f"/jobs/{second}/execution-finish", headers=runner_headers,
                json={**payload, "token": response.json()["execution_control"]["token"], "outcome": "failed"})


@pytest.mark.parametrize("body", [{}, {"limit": 1}, {"limit_seconds": True}, {"limit_seconds": "1"}, {"limit_seconds": 0}, {"limit_seconds": 1000000001}, {"limit_seconds": 1, "reset": True}])
def test_strict_current_owner_configuration(client, program_id, auth_headers, runner_headers, other_headers, body):
    assert policy(client, program_id, runner_headers, 1).status_code == 403
    assert policy(client, program_id, other_headers, 1).status_code == 404
    assert policy(client, program_id, auth_headers, 1).status_code == 200
    assert client.put(f"/engagements/{program_id}/duration-policy", headers=auth_headers, json=body).status_code == 422
    with _SessionLocal() as db:
        assert db.get(Engagement, program_id).duration_limit == 1


def test_no_legacy_bypass_and_all_counters_rollback_together(client, program_id, auth_headers, runner_headers):
    spec = _spec()
    ident = queued(client, program_id, auth_headers, spec)
    assert policy(client, program_id, auth_headers, 1).status_code == 200
    assert client.put(f"/engagements/{program_id}/target-policy", headers=auth_headers, json={"limit": 2}).status_code == 200
    assert client.put(f"/engagements/{program_id}/concurrency-policy", headers=auth_headers, json={"limit": 1}).status_code == 200
    assert client.post(f"/jobs/{ident}/claim", headers=runner_headers).status_code == 409
    payload = {"runner_id": str(uuid.uuid4()), "origin": "http://localhost", "concurrency_budget": True,
               "target_binding": binding(spec), "duration_seconds": 2}
    assert client.post(f"/jobs/{ident}/claim", headers=runner_headers, json=payload).status_code == 409
    with _SessionLocal() as db:
        engagement = db.get(Engagement, program_id)
        assert engagement.duration_allocated == engagement.targets_spent == 0
        assert db.get(JobExecution, ident) is None


def test_policy_refuses_unaccounted_running_work_and_viewer(client, program_id, auth_headers, other_headers, runner_headers):
    assert client.post(f"/engagements/{program_id}/members", headers=auth_headers, json={"github_id": "gh_user2", "role": "viewer"}).status_code == 201
    assert policy(client, program_id, other_headers, 1).status_code == 403
    ident = job(client, program_id, auth_headers)
    assert client.post(f"/jobs/{ident}/claim", headers=runner_headers).status_code == 200
    assert policy(client, program_id, auth_headers, 1).status_code == 409


def test_claim_requires_configured_policy_and_finite_integer(client, program_id, auth_headers, runner_headers):
    ident = job(client, program_id, auth_headers)
    assert claim(client, ident, runner_headers, 1)[0].status_code == 409
    assert policy(client, program_id, auth_headers, 2).status_code == 200
    assert client.post(f"/jobs/{ident}/claim", headers=runner_headers).status_code == 409
    for seconds in [None, True, 0, -1, 86401, "1", 1.5]:
        assert claim(client, ident, runner_headers, seconds)[0].status_code == (409 if seconds is None else 422)
    with _SessionLocal() as db:
        assert db.get(Engagement, program_id).duration_allocated == 0
        assert db.get(JobExecution, ident) is None
