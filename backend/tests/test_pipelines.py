"""Tests for pipeline job chaining, dependency gating, and dry-run preview."""


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

    # Complete the parent → child becomes eligible.
    client.patch(f"/jobs/{parent_id}", json={"status": "done"}, headers=auth_headers)
    pending2 = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    assert child_id in {j["id"] for j in pending2}


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
