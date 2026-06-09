"""Tests for the scan_jobs endpoints.

Coverage:
- POST /programs/{id}/jobs — create job
- GET  /programs/{id}/jobs — list jobs
- GET  /jobs/pending       — VardrRunner poll endpoint
- PATCH /jobs/{id}         — status update

BOLA checks: wrong-user can't see or modify another user's jobs.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_job(client, program_id, headers, **overrides):
    payload = {
        "tool_type": "httpx",
        "target_source": "scope",
        **overrides,
    }
    return client.post(f"/programs/{program_id}/jobs", json=payload, headers=headers)


# ---------------------------------------------------------------------------
# POST /programs/{id}/jobs
# ---------------------------------------------------------------------------

class TestCreateJob:
    def test_create_success(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["tool_type"] == "httpx"
        assert data["target_source"] == "scope"
        assert data["status"] == "pending"
        assert data["program_id"] == program_id
        assert data["id"]

    def test_create_with_config(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="nuclei",
                          target_source="recon",
                          config={"severity": "high", "templates": ["cves"]})
        assert res.status_code == 200
        assert res.json()["config"]["severity"] == "high"

    def test_subfinder_tool_accepted(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="subfinder", target_source="scope",
                          config={"recursive": True, "sources": "crtsh"})
        assert res.status_code == 200
        assert res.json()["tool_type"] == "subfinder"

    def test_invalid_tool_type(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers, tool_type="nmap")
        assert res.status_code == 400

    def test_invalid_target_source(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers, target_source="internet")
        assert res.status_code == 400

    def test_unauthorized(self, client, program_id):
        res = _create_job(client, program_id, {})
        assert res.status_code == 401

    def test_wrong_user_404(self, client, program_id, other_headers):
        res = _create_job(client, program_id, other_headers)
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# GET /programs/{id}/jobs
# ---------------------------------------------------------------------------

class TestListJobs:
    def test_list_empty(self, client, program_id, auth_headers):
        res = client.get(f"/programs/{program_id}/jobs", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["jobs"] == []

    def test_list_returns_own_jobs(self, client, program_id, auth_headers):
        _create_job(client, program_id, auth_headers)
        _create_job(client, program_id, auth_headers, tool_type="nuclei")
        res = client.get(f"/programs/{program_id}/jobs", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()["jobs"]) >= 2

    def test_list_unauthorized(self, client, program_id):
        res = client.get(f"/programs/{program_id}/jobs")
        assert res.status_code == 401

    def test_list_wrong_user_404(self, client, program_id, other_headers):
        res = client.get(f"/programs/{program_id}/jobs", headers=other_headers)
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# GET /jobs/pending
# ---------------------------------------------------------------------------

class TestPendingJobs:
    def test_pending_returns_only_pending(self, client, program_id, auth_headers):
        _create_job(client, program_id, auth_headers)
        res = client.get("/jobs/pending", headers=auth_headers)
        assert res.status_code == 200
        jobs = res.json()["jobs"]
        assert all(j["status"] == "pending" for j in jobs)

    def test_pending_excludes_done_jobs(self, client, program_id, auth_headers):
        cr = _create_job(client, program_id, auth_headers)
        jid = cr.json()["id"]
        client.patch(f"/jobs/{jid}", json={"status": "done"}, headers=auth_headers)

        res = client.get("/jobs/pending", headers=auth_headers)
        job_ids = [j["id"] for j in res.json()["jobs"]]
        assert jid not in job_ids

    def test_pending_excludes_other_users_jobs(self, client, program_id, auth_headers, other_headers):
        _create_job(client, program_id, auth_headers)
        res = client.get("/jobs/pending", headers=other_headers)
        assert res.json()["jobs"] == []

    def test_pending_unauthorized(self, client):
        res = client.get("/jobs/pending")
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /jobs/{id}
# ---------------------------------------------------------------------------

class TestUpdateJob:
    def test_mark_running(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.patch(f"/jobs/{jid}", json={"status": "running"}, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "running"
        assert data["started_at"] is not None

    def test_mark_done(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.patch(f"/jobs/{jid}", json={"status": "done"}, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "done"
        assert data["completed_at"] is not None

    def test_mark_failed_with_error(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.patch(f"/jobs/{jid}", json={"status": "failed", "error_message": "timeout"}, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "timeout"
        assert data["completed_at"] is not None

    def test_invalid_status(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.patch(f"/jobs/{jid}", json={"status": "cancelled"}, headers=auth_headers)
        assert res.status_code == 400

    def test_wrong_user_404(self, client, program_id, auth_headers, other_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.patch(f"/jobs/{jid}", json={"status": "running"}, headers=other_headers)
        assert res.status_code == 404

    def test_unauthorized(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.patch(f"/jobs/{jid}", json={"status": "running"})
        assert res.status_code == 401

    def test_nonexistent_job_404(self, client, auth_headers):
        res = client.patch("/jobs/does-not-exist", json={"status": "running"}, headers=auth_headers)
        assert res.status_code == 404
