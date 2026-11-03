"""Owned control against disposable database state; no scan auto-start."""

import hashlib
import uuid
from datetime import timedelta

import pytest

from tests.conftest import _SessionLocal
from execution_control import now
from models import ApiKey, JobExecution, ScanJob


@pytest.fixture
def runner_headers(client, auth_headers):
    token = "vmap_" + uuid.uuid4().hex
    with _SessionLocal() as db:
        db.add(
            ApiKey(
                id=str(uuid.uuid4()),
                github_id="gh_user1",
                label="disposable control fixture",
                scope="runner",
                key_hash=hashlib.sha256(token.encode()).hexdigest(),
            )
        )
        db.commit()
    yield {"Authorization": "Bearer " + token}
    with _SessionLocal() as db:
        db.query(ApiKey).filter_by(
            key_hash=hashlib.sha256(token.encode()).hexdigest()
        ).delete()
        db.commit()


def claimed(client, program_id, auth_headers, runner_headers):
    response = client.post(
        f"/engagements/{program_id}/jobs",
        headers=auth_headers,
        json={"tool_type": "httpx", "target_source": "scope"},
    )
    assert response.status_code == 200, response.text
    job = response.json()["id"]
    binding = {"runner_id": str(uuid.uuid4()), "origin": "http://localhost"}
    response = client.post(f"/jobs/{job}/claim", headers=runner_headers, json=binding)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return job, {**binding, "token": response.json()["execution_control"]["token"]}


def test_owned_cancel_and_no_forged_completion(
    client, program_id, auth_headers, runner_headers
):
    job, payload = claimed(client, program_id, auth_headers, runner_headers)
    assert (
        client.post(
            f"/jobs/{job}/control", headers=runner_headers, json=payload
        ).json()["action"]
        == "continue"
    )
    assert (
        client.patch(
            f"/jobs/{job}", headers=auth_headers, json={"status": "done"}
        ).status_code
        == 409
    )
    response = client.patch(
        f"/jobs/{job}",
        headers=auth_headers,
        json={"status": "failed", "error_message": "cancelled by operator"},
    )
    assert response.json()["status"] == "running"
    assert response.json()["execution_state"] == "cancel_requested"
    assert (
        client.post(
            f"/jobs/{job}/control", headers=runner_headers, json=payload
        ).json()["action"]
        == "cancel"
    )
    assert (
        client.post(
            f"/jobs/{job}/execution-finish",
            headers=runner_headers,
            json={**payload, "outcome": "completed"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/jobs/{job}/execution-finish",
            headers=runner_headers,
            json={**payload, "outcome": "cancelled"},
        ).json()["state"]
        == "cancelled"
    )
    with _SessionLocal() as db:
        assert db.get(ScanJob, job).status == "failed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("token", "x" * 40),
        ("origin", "http://127.0.0.1"),
        ("runner_id", str(uuid.uuid4())),
    ],
)
def test_wrong_binding(client, program_id, auth_headers, runner_headers, field, value):
    job, payload = claimed(client, program_id, auth_headers, runner_headers)
    assert (
        client.post(
            f"/jobs/{job}/control",
            headers=runner_headers,
            json={**payload, field: value},
        ).status_code
        == 404
    )


def test_other_principal_and_cross_job(
    client, program_id, auth_headers, other_headers, runner_headers
):
    job, payload = claimed(client, program_id, auth_headers, runner_headers)
    for headers in [other_headers, auth_headers]:
        assert client.post(
            f"/jobs/{job}/control", headers=headers, json=payload
        ).status_code in {403, 404}
    other_job, _ = claimed(client, program_id, auth_headers, runner_headers)
    assert (
        client.post(
            f"/jobs/{other_job}/control", headers=runner_headers, json=payload
        ).status_code
        == 404
    )


def test_stop_sticky_after_release(client, program_id, auth_headers, runner_headers):
    job, payload = claimed(client, program_id, auth_headers, runner_headers)
    # Queue before stop; claim after stop must be denied.
    pending = client.post(
        f"/engagements/{program_id}/jobs",
        headers=auth_headers,
        json={"tool_type": "httpx", "target_source": "scope"},
    ).json()["id"]
    assert (
        client.post(
            f"/engagements/{program_id}/stop-work",
            headers=auth_headers,
            json={"reason": "controlled stop"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/jobs/{pending}/claim",
            headers=runner_headers,
            json={"runner_id": str(uuid.uuid4()), "origin": "http://localhost"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/engagements/{program_id}/stop-work", headers=auth_headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/jobs/{job}/control", headers=runner_headers, json=payload
        ).json()["action"]
        == "cancel"
    )


def test_expired_lease_never_resurrects(
    client, program_id, auth_headers, runner_headers
):
    job, payload = claimed(client, program_id, auth_headers, runner_headers)
    with _SessionLocal() as db:
        db.get(JobExecution, job).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert (
        client.post(
            f"/jobs/{job}/control", headers=runner_headers, json=payload
        ).json()["action"]
        == "cancel"
    )
    assert (
        client.post(
            f"/jobs/{job}/execution-finish",
            headers=runner_headers,
            json={**payload, "outcome": "completed"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/jobs/{job}/execution-finish",
            headers=runner_headers,
            json={**payload, "outcome": "uncertain"},
        ).json()["state"]
        == "uncertain"
    )
    with _SessionLocal() as db:
        assert db.get(ScanJob, job).status == "running"
    assert client.post(f"/jobs/{job}/claim", headers=runner_headers).status_code == 409


def test_duplicate_completion_and_revoked_key(
    client, program_id, auth_headers, runner_headers
):
    job, payload = claimed(client, program_id, auth_headers, runner_headers)
    for _ in range(2):
        assert (
            client.post(
                f"/jobs/{job}/execution-finish",
                headers=runner_headers,
                json={**payload, "outcome": "completed"},
            ).status_code
            == 200
        )
    with _SessionLocal() as db:
        key_hash = hashlib.sha256(
            runner_headers["Authorization"][7:].encode()
        ).hexdigest()
        db.query(ApiKey).filter_by(key_hash=key_hash).delete()
        db.commit()
    assert (
        client.post(
            f"/jobs/{job}/control", headers=runner_headers, json=payload
        ).status_code
        == 401
    )


def test_control_capability_not_reflected_in_validation_error(
    client, program_id, auth_headers, runner_headers
):
    job, payload = claimed(client, program_id, auth_headers, runner_headers)
    for suffix in ["control", "execution-finish"]:
        response = client.post(
            f"/jobs/{job}/{suffix}",
            headers=runner_headers,
            json={**payload, "unexpected": payload["token"]},
        )
        assert response.status_code == 422
        assert payload["token"] not in response.text
        assert response.headers["cache-control"] == "no-store"
