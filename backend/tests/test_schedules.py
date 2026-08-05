"""Scheduled scans: CRUD, validation, materialization into pending jobs, BOLA."""

_SCHEDULE = {"tool_type": "httpx", "target_source": "scope", "config": {"limit": 50}, "interval": "daily"}


def _pending_for(client, auth_headers, program_id):
    """Pending jobs filtered to one engagement (the shared test DB accumulates jobs)."""
    jobs = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    return [j for j in jobs if j["program_id"] == program_id]


# ---------------------------------------------------------------------------
# CRUD + validation
# ---------------------------------------------------------------------------

def test_create_schedule(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["tool_type"] == "httpx"
    assert data["interval"] == "daily"
    assert data["enabled"] is True
    assert data["next_run_at"] is not None
    assert data["last_run_at"] is None


def test_create_invalid_interval_rejected(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/schedules",
                      json={**_SCHEDULE, "interval": "monthly"}, headers=auth_headers)
    assert res.status_code == 400


def test_create_invalid_tool_rejected(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/schedules",
                      json={**_SCHEDULE, "tool_type": "masscan"}, headers=auth_headers)
    assert res.status_code == 400


def test_create_invalid_config_rejected(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/schedules",
                      json={**_SCHEDULE, "config": {"bogus_key": 1}}, headers=auth_headers)
    assert res.status_code == 400


def test_list_schedules(client, auth_headers, program_id):
    client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers)
    res = client.get(f"/programs/{program_id}/schedules", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 1


def test_update_schedule(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/schedules/{sid}",
                       json={"enabled": False, "interval": "weekly"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is False
    assert data["interval"] == "weekly"


def test_update_invalid_interval_rejected(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/schedules/{sid}",
                       json={"interval": "yearly"}, headers=auth_headers)
    assert res.status_code == 400


def test_delete_schedule(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/schedules/{sid}", headers=auth_headers)
    assert res.status_code == 200
    ids = [s["id"] for s in client.get(f"/programs/{program_id}/schedules", headers=auth_headers).json()["schedules"]]
    assert sid not in ids


def test_update_nonexistent_returns_404(client, auth_headers, program_id):
    res = client.patch(f"/programs/{program_id}/schedules/nonexistent",
                       json={"enabled": False}, headers=auth_headers)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Materialization — due schedules become pending jobs when the runner polls
# ---------------------------------------------------------------------------

def test_due_schedule_materializes_job_on_poll(client, auth_headers, program_id):
    client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers)
    # New schedules are due immediately — the first poll creates the job
    jobs = _pending_for(client, auth_headers, program_id)
    assert len(jobs) == 1
    assert jobs[0]["tool_type"] == "httpx"
    assert jobs[0]["config"] == {"limit": 50}


def test_materialization_advances_next_run(client, auth_headers, program_id):
    created = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers).json()
    client.get("/jobs/pending", headers=auth_headers)  # triggers materialization
    after = client.get(f"/programs/{program_id}/schedules", headers=auth_headers).json()["schedules"]
    schedule = next(s for s in after if s["id"] == created["id"])
    assert schedule["last_run_at"] is not None
    assert schedule["next_run_at"] > created["next_run_at"]


def test_schedule_does_not_fire_twice_immediately(client, auth_headers, program_id):
    client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers)
    client.get("/jobs/pending", headers=auth_headers)  # first poll materializes
    jobs = _pending_for(client, auth_headers, program_id)  # second poll must not duplicate
    assert len(jobs) == 1


def test_disabled_schedule_not_materialized(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers).json()["id"]
    client.patch(f"/programs/{program_id}/schedules/{sid}", json={"enabled": False}, headers=auth_headers)
    jobs = _pending_for(client, auth_headers, program_id)
    assert len(jobs) == 0


# ---------------------------------------------------------------------------
# BOLA checks
# ---------------------------------------------------------------------------

def test_create_in_other_users_program_returns_404(client, other_headers, program_id):
    res = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=other_headers)
    assert res.status_code == 404


def test_list_other_users_program_returns_404(client, other_headers, program_id):
    res = client.get(f"/programs/{program_id}/schedules", headers=other_headers)
    assert res.status_code == 404


def test_update_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    sid = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/schedules/{sid}", json={"enabled": False}, headers=other_headers)
    assert res.status_code == 404


def test_delete_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    sid = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/schedules/{sid}", headers=other_headers)
    assert res.status_code == 404


def test_other_users_due_schedule_not_materialized_for_me(client, auth_headers, other_headers, program_id):
    """user1's due schedule must not create jobs when user2 polls."""
    client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE, headers=auth_headers)
    client.get("/jobs/pending", headers=other_headers)  # user2 polls first
    # user1's schedule should still be unfired (user2's poll must not touch it)
    schedules = client.get(f"/programs/{program_id}/schedules", headers=auth_headers).json()["schedules"]
    assert all(s["last_run_at"] is None for s in schedules)


# ---------------------------------------------------------------------------
# Auth checks
# ---------------------------------------------------------------------------

def test_list_unauthorized(client, program_id):
    res = client.get(f"/programs/{program_id}/schedules")
    assert res.status_code == 401


def test_create_unauthorized(client, program_id):
    res = client.post(f"/programs/{program_id}/schedules", json=_SCHEDULE)
    assert res.status_code == 401
