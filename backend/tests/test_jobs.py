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

    def test_nmap_tool_accepted(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="nmap", target_source="scope",
                          config={"top_ports": 100, "timing": 3})
        assert res.status_code == 200
        assert res.json()["tool_type"] == "nmap"

    def test_dnsx_tool_accepted(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="dnsx", target_source="recon",
                          config={"limit": 500})
        assert res.status_code == 200
        assert res.json()["tool_type"] == "dnsx"

    def test_naabu_tool_accepted(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="naabu", target_source="scope",
                          config={"top_ports": 100, "limit": 500})
        assert res.status_code == 200
        assert res.json()["tool_type"] == "naabu"

    def test_naabu_rejects_out_of_range_top_ports(self, client, program_id, auth_headers):
        """Bounds mirror VardrRunner's own, so a bad value fails at queue time
        rather than on the operator's machine after the job is claimed."""
        res = _create_job(client, program_id, auth_headers,
                          tool_type="naabu", target_source="scope",
                          config={"top_ports": 70000})
        assert res.status_code == 400
        assert "top_ports" in res.text

    def test_dnsx_rejects_a_non_integer_limit(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="dnsx", target_source="recon",
                          config={"limit": "lots"})
        assert res.status_code == 400

    def test_dnsx_rejects_unknown_config_keys(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="dnsx", target_source="recon",
                          config={"severity": "high"})
        assert res.status_code == 400

    def test_vardrgate_is_not_queueable_yet(self, client, program_id, auth_headers):
        """VardrRunner has a handler, but VardrMap has no /jobs/{id}/upload endpoint
        and no test_case model — so it stays out of _VALID_TOOLS until both exist."""
        res = _create_job(client, program_id, auth_headers, tool_type="vardrgate_api_test")
        assert res.status_code == 400

    def test_invalid_tool_type(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers, tool_type="masscan")
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


# ---------------------------------------------------------------------------
# POST /jobs/{id}/claim — atomic job claiming
# ---------------------------------------------------------------------------

class TestClaimJob:
    def test_claim_success(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.post(f"/jobs/{jid}/claim", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "running"
        assert data["started_at"] is not None

    def test_claim_already_running_returns_409(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        client.post(f"/jobs/{jid}/claim", headers=auth_headers)
        res = client.post(f"/jobs/{jid}/claim", headers=auth_headers)
        assert res.status_code == 409

    def test_claim_done_job_returns_409(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        client.patch(f"/jobs/{jid}", json={"status": "done"}, headers=auth_headers)
        res = client.post(f"/jobs/{jid}/claim", headers=auth_headers)
        assert res.status_code == 409

    def test_claim_wrong_user_404(self, client, program_id, auth_headers, other_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.post(f"/jobs/{jid}/claim", headers=other_headers)
        assert res.status_code == 404

    def test_claim_unauthorized(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.post(f"/jobs/{jid}/claim")
        assert res.status_code == 401

    def test_claim_nonexistent_404(self, client, auth_headers):
        res = client.post("/jobs/does-not-exist/claim", headers=auth_headers)
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

class TestDeleteJob:
    def test_delete_pending_job(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.delete(f"/jobs/{jid}", headers=auth_headers)
        assert res.status_code == 200
        ids = [j["id"] for j in client.get(f"/programs/{program_id}/jobs", headers=auth_headers).json()["jobs"]]
        assert jid not in ids

    def test_delete_stuck_running_job(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        client.patch(f"/jobs/{jid}", json={"status": "running"}, headers=auth_headers)
        res = client.delete(f"/jobs/{jid}", headers=auth_headers)
        assert res.status_code == 200

    def test_delete_done_job(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        client.patch(f"/jobs/{jid}", json={"status": "done"}, headers=auth_headers)
        res = client.delete(f"/jobs/{jid}", headers=auth_headers)
        assert res.status_code == 200

    def test_delete_nonexistent_returns_404(self, client, auth_headers):
        res = client.delete("/jobs/does-not-exist", headers=auth_headers)
        assert res.status_code == 404

    def test_delete_wrong_user_returns_404(self, client, program_id, auth_headers, other_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.delete(f"/jobs/{jid}", headers=other_headers)
        assert res.status_code == 404

    def test_delete_unauthorized(self, client, program_id, auth_headers):
        jid = _create_job(client, program_id, auth_headers).json()["id"]
        res = client.delete(f"/jobs/{jid}")
        assert res.status_code == 401


class TestJobConfigValidation:
    def test_unknown_config_key_rejected(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="httpx", config={"unknown_key": True})
        assert res.status_code == 400

    def test_nuclei_invalid_severity_rejected(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="nuclei", config={"severity": "extreme"})
        assert res.status_code == 400

    def test_nmap_timing_out_of_range_rejected(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="nmap", config={"timing": 5})
        assert res.status_code == 400

    def test_nmap_valid_config_accepted(self, client, program_id, auth_headers):
        res = _create_job(client, program_id, auth_headers,
                          tool_type="nmap", config={"top_ports": 200, "timing": 4})
        assert res.status_code == 200
