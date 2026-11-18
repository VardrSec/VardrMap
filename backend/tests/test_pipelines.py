"""Tests for pipeline job chaining, dependency gating, and dry-run preview."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from models import Engagement, JobExecution, ScanJob
from target_budget import binding
from tests.conftest import _SessionLocal
from tests.test_execution_control import runner_headers as runner_headers
from tests.test_target_budget import queued
from tests.test_vardrgate_jobs import _spec


def _add_scope(client, headers, program_id, value):
    return client.post(
        f"/programs/{program_id}/scope/in",
        json={"value": value, "kind": "domain"},
        headers=headers,
    )


def test_create_pipeline_chains_dependencies(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/pipelines",
        json={"stages": [
            {"tool_type": "subfinder", "target_source": "scope"},
            {"tool_type": "httpx", "target_source": "recon"},
            {"tool_type": "nuclei", "target_source": "recon", "config": {"severity": "high,critical"}},
        ]},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    jobs = res.json()["jobs"]
    assert len(jobs) == 3
    # First stage has no dependency; each subsequent stage depends on the prior.
    assert jobs[0]["depends_on"] is None
    assert jobs[1]["depends_on"] == jobs[0]["id"]
    assert jobs[2]["depends_on"] == jobs[1]["id"]


def test_pipeline_chains_a_subset_without_a_dangling_wait(client, auth_headers, program_id):
    """The Composer's stage editor posts only the stages the operator included.

    Dropping the middle stage must chain the survivors to each other — a stage
    left waiting on a job that was never created would hang in `pending` forever.
    """
    res = client.post(
        f"/programs/{program_id}/pipelines",
        json={"stages": [
            {"tool_type": "subfinder", "target_source": "scope"},
            {"tool_type": "nuclei", "target_source": "recon"},
        ]},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    jobs = res.json()["jobs"]
    assert [j["tool_type"] for j in jobs] == ["subfinder", "nuclei"]
    assert jobs[0]["depends_on"] is None
    assert jobs[1]["depends_on"] == jobs[0]["id"]


def test_single_stage_pipeline_has_no_dependency(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/pipelines",
        json={"stages": [{"tool_type": "httpx", "target_source": "recon"}]},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    jobs = res.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["depends_on"] is None


def test_pipeline_rejects_an_empty_stage_list(client, auth_headers, program_id):
    """Backs the Composer disabling Queue at zero stages — the API refuses it too."""
    res = client.post(
        f"/programs/{program_id}/pipelines",
        json={"stages": []},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_pipeline_rejects_bad_stage_atomically(client, auth_headers, program_id):
    before = client.get(f"/programs/{program_id}/jobs", headers=auth_headers).json()["jobs"]
    res = client.post(
        f"/programs/{program_id}/pipelines",
        json={"stages": [
            {"tool_type": "subfinder", "target_source": "scope"},
            {"tool_type": "notatool", "target_source": "scope"},
        ]},
        headers=auth_headers,
    )
    assert res.status_code == 400
    after = client.get(f"/programs/{program_id}/jobs", headers=auth_headers).json()["jobs"]
    assert len(after) == len(before), "no jobs should be created when a stage is invalid"


def test_pending_holds_dependent_until_parent_done(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/pipelines",
        json={"stages": [
            {"tool_type": "subfinder", "target_source": "scope"},
            {"tool_type": "httpx", "target_source": "recon"},
        ]},
        headers=auth_headers,
    )
    parent_id, child_id = [j["id"] for j in res.json()["jobs"]]

    pending = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    ids = {j["id"] for j in pending}
    assert parent_id in ids, "parent (no dependency) should be eligible"
    assert child_id not in ids, "child should be held until parent is done"

    def assert_child_held():
        response = client.post(f"/jobs/{child_id}/claim", headers=auth_headers)
        assert response.status_code == 409
        assert "dependency" in response.json()["detail"]
        with _SessionLocal() as db:
            child = db.get(ScanJob, child_id)
            assert child.status == "pending" and child.started_at is None

    assert_child_held()
    assert client.post(f"/jobs/{parent_id}/claim", headers=auth_headers).status_code == 200
    assert_child_held()
    assert client.patch(f"/jobs/{parent_id}", json={"status": "done"}, headers=auth_headers).status_code == 200
    pending2 = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    assert child_id in {j["id"] for j in pending2}
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(client.post, f"/jobs/{child_id}/claim", headers=auth_headers) for _ in range(2)]
        responses = sorted((attempt.result() for attempt in attempts), key=lambda r: r.status_code)
    winner, loser = responses
    assert winner.status_code == 200 and loser.status_code == 409
    assert winner.json()["status"] == "running" and winner.json()["started_at"] is not None
    assert loser.json()["detail"] == "job is already running"


@pytest.mark.parametrize("parent_exists", [True, False], ids=["failed-parent", "missing-parent"])
def test_blocked_dependency_spends_no_budget_or_credentials(
    client, auth_headers, runner_headers, program_id, parent_exists,
):
    spec = _spec()
    child_id = queued(client, program_id, auth_headers, spec)
    parent_id = str(uuid.uuid4())
    with _SessionLocal() as db:
        if parent_exists:
            db.add(ScanJob(id=parent_id, program_id=program_id, owner_github_id="gh_user1",
                           tool_type="httpx", target_source="scope", status="failed"))
        db.get(ScanJob, child_id).depends_on = parent_id
        engagement = db.get(Engagement, program_id)
        engagement.concurrency_limit = engagement.target_limit = engagement.duration_limit = 1
        db.commit()

    response = client.post(f"/jobs/{child_id}/claim", headers=runner_headers, json={
        "runner_id": str(uuid.uuid4()), "origin": "http://localhost", "concurrency_budget": True,
        "target_binding": binding(spec), "duration_seconds": 1,
    })
    assert response.status_code == 409
    assert set(response.json()) == {"detail"}
    assert "dependency" in response.json()["detail"]
    with _SessionLocal() as db:
        child = db.get(ScanJob, child_id)
        assert child.status == "pending" and child.started_at is None and child.case_snapshot is None
        assert db.get(JobExecution, child_id) is None
        engagement = db.get(Engagement, program_id)
        assert engagement.targets_spent == engagement.duration_allocated == 0


def test_pending_autofails_child_when_parent_fails(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/pipelines",
        json={"stages": [
            {"tool_type": "subfinder", "target_source": "scope"},
            {"tool_type": "httpx", "target_source": "recon"},
        ]},
        headers=auth_headers,
    )
    parent_id, child_id = [j["id"] for j in res.json()["jobs"]]

    client.patch(f"/jobs/{parent_id}", json={"status": "failed", "error_message": "boom"}, headers=auth_headers)
    pending = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    assert child_id not in {j["id"] for j in pending}

    jobs = client.get(f"/programs/{program_id}/jobs", headers=auth_headers).json()["jobs"]
    child = next(j for j in jobs if j["id"] == child_id)
    assert child["status"] == "failed"
    assert "upstream" in child["error_message"]


def test_create_job_rejects_foreign_dependency(client, auth_headers, other_headers, program_id):
    # A job created by another user cannot be used as a dependency.
    other_prog = client.post("/programs", json={"name": "Other"}, headers=other_headers).json()["id"]
    other_job = client.post(
        f"/programs/{other_prog}/jobs",
        json={"tool_type": "subfinder", "target_source": "scope"},
        headers=other_headers,
    ).json()["id"]

    res = client.post(
        f"/programs/{program_id}/jobs",
        json={"tool_type": "httpx", "target_source": "recon", "depends_on": other_job},
        headers=auth_headers,
    )
    assert res.status_code == 400
    # A stored reference to a completed job across engagements cannot authorize a claim.
    with _SessionLocal() as db:
        db.get(ScanJob, other_job).status = "done"
        child = ScanJob(program_id=program_id, owner_github_id="gh_user1", tool_type="httpx",
                        target_source="scope", depends_on=other_job)
        db.add(child)
        db.commit()
        child_id = child.id
    res = client.post(f"/jobs/{child_id}/claim", headers=auth_headers)
    assert res.status_code == 409 and "dependency" in res.json()["detail"]
    client.delete(f"/programs/{other_prog}", headers=other_headers)


def test_preview_counts_scope_targets(client, auth_headers, program_id):
    _add_scope(client, auth_headers, program_id, "a.example.com")
    _add_scope(client, auth_headers, program_id, "b.example.com")
    res = client.post(
        f"/programs/{program_id}/jobs/preview",
        json={"tool_type": "subfinder", "target_source": "scope"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 2
    assert set(body["sample"]) == {"a.example.com", "b.example.com"}
    assert body["truncated"] is False


def test_preview_bola_returns_404(client, other_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/jobs/preview",
        json={"tool_type": "subfinder", "target_source": "scope"},
        headers=other_headers,
    )
    assert res.status_code == 404


def test_preview_requires_auth(client, program_id):
    res = client.post(
        f"/programs/{program_id}/jobs/preview",
        json={"tool_type": "subfinder", "target_source": "scope"},
    )
    assert res.status_code == 401
