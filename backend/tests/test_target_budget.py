"""Cumulative target accounting against disposable fixture state only."""
import uuid
import pytest

from tests.conftest import _SessionLocal
from tests.test_execution_control import runner_headers as runner_headers
from tests.test_vardrgate_jobs import _spec, _queue
from models import Engagement, JobExecution
from target_budget import binding


@pytest.fixture(autouse=True)
def reset_disposable_fixture_counter(program_id):
    yield
    # Test-only teardown; the product deliberately has no reset/delete bypass.
    with _SessionLocal() as db:
        row = db.get(Engagement, program_id)
        if row is not None:
            row.targets_spent = 0
            db.commit()


def configure(client, eng, headers, limit):
    return client.put(f"/engagements/{eng}/target-policy", headers=headers, json={"limit": limit})


def queued(client, eng, headers, spec):
    result = client.post(f"/engagements/{eng}/test-cases", headers=headers, json={"name": "synthetic", "spec": spec})
    assert result.status_code == 201, result.text
    result = _queue(client, headers, eng, result.json()["id"])
    assert result.status_code == 200, result.text
    return result.json()["id"]


def claim(client, ident, headers, spec, changes=None):
    target = binding(spec)
    if changes:
        target.update(changes)
    payload = {"runner_id": str(uuid.uuid4()), "origin": "http://localhost", "target_binding": target}
    return client.post(f"/jobs/{ident}/claim", headers=headers, json=payload), payload


def test_cumulative_charge_survives_finish_delete_and_policy(client, program_id, auth_headers, runner_headers):
    spec = _spec()
    spec["setup"] = [{"name": "aux", "request": {"method": "GET", "url": "https://setup.example.test/start"}}]
    assert configure(client, program_id, auth_headers, 2).status_code == 200
    first = queued(client, program_id, auth_headers, spec)
    second = queued(client, program_id, auth_headers, spec)
    response, payload = claim(client, first, runner_headers, spec)
    assert response.status_code == 200, response.text
    receipt = response.json()["execution_control"]
    assert receipt["target_budget"]["charged"] == 2
    assert claim(client, first, runner_headers, spec)[0].status_code == 409
    for outcome in ["uncertain", "cancelled", "cancelled"]:
        result = client.post(f"/jobs/{first}/execution-finish", headers=runner_headers,
                             json={**payload, "token": receipt["token"], "outcome": outcome})
        assert result.status_code == 200, result.text
    assert client.delete(f"/jobs/{first}", headers=auth_headers).status_code == 200
    assert claim(client, second, runner_headers, spec)[0].status_code == 409
    assert configure(client, program_id, auth_headers, None).status_code == 409
    assert configure(client, program_id, auth_headers, 1).status_code == 409
    assert client.delete(f"/engagements/{program_id}", headers=auth_headers).status_code == 409
    assert configure(client, program_id, auth_headers, 4).json()["spent"] == 2
    response, payload = claim(client, second, runner_headers, spec)
    assert response.status_code == 200
    assert response.json()["execution_control"]["target_budget"]["spent"] == 4
    client.post(f"/jobs/{second}/execution-finish", headers=runner_headers,
                json={**payload, "token": response.json()["execution_control"]["token"], "outcome": "failed"})


@pytest.mark.parametrize("changes", [{"origins": ["https://wrong.example:443"]}, {"case_sha256": "0"*64}])
def test_mismatched_binding_is_not_charged(client, program_id, auth_headers, runner_headers, changes):
    spec = _spec()
    assert configure(client, program_id, auth_headers, 1).status_code == 200
    ident = queued(client, program_id, auth_headers, spec)
    assert claim(client, ident, runner_headers, spec, changes)[0].status_code == 409
    with _SessionLocal() as db:
        assert db.get(Engagement, program_id).targets_spent == 0
        assert db.get(JobExecution, ident) is None


@pytest.mark.parametrize("body", [{}, {"limt": 1}, {"limit": True}, {"limit": 0}, {"limit": "1"}, {"limit": 1, "reset": True}])
def test_explicit_owner_configuration_only(client, program_id, auth_headers, runner_headers, other_headers, body):
    assert configure(client, program_id, runner_headers, 1).status_code == 403
    assert configure(client, program_id, other_headers, 1).status_code == 404
    assert configure(client, program_id, auth_headers, 1).status_code == 200
    result = client.put(f"/engagements/{program_id}/target-policy", headers=auth_headers, json=body)
    assert result.status_code == 422
    with _SessionLocal() as db:
        assert db.get(Engagement, program_id).target_limit == 1


def test_binding_covers_every_represented_auxiliary_origin():
    spec = _spec()
    spec["setup"] = [{"request": {"url": "https://SETUP.example/start"}}]
    spec["identities"][0]["preflight"] = {"url": "https://preflight.example/me"}
    spec["write_verification"] = {"identity": {"id": "reader", "preflight": {"url": "https://reader.example/me"}},
                                  "request": {"url": "https://verify.example/read"},
                                  "reset": {"request": {"url": "https://reset.example/reset"}}}
    assert len(binding(spec)["origins"]) == 6


def test_viewer_and_unbounded_profile_cannot_bypass(client, program_id, auth_headers, other_headers, runner_headers):
    result = client.post(f"/engagements/{program_id}/members", headers=auth_headers, json={"github_id": "gh_user2", "role": "viewer"})
    assert result.status_code == 201
    assert configure(client, program_id, other_headers, 1).status_code == 403
    assert configure(client, program_id, auth_headers, 1).status_code == 200
    result = client.post(f"/engagements/{program_id}/jobs", headers=auth_headers, json={"tool_type": "httpx", "target_source": "scope"})
    ident = result.json()["id"]
    assert client.post(f"/jobs/{ident}/claim", headers=runner_headers).status_code == 409
    assert claim(client, ident, runner_headers, _spec())[0].status_code == 409
    with _SessionLocal() as db:
        assert db.get(Engagement, program_id).targets_spent == 0


def test_target_policy_refuses_running_unaccounted_work(client, program_id, auth_headers, runner_headers):
    result = client.post(f"/engagements/{program_id}/jobs", headers=auth_headers, json={"tool_type": "httpx", "target_source": "scope"})
    assert client.post(f"/jobs/{result.json()['id']}/claim", headers=runner_headers).status_code == 200
    assert configure(client, program_id, auth_headers, 1).status_code == 409
