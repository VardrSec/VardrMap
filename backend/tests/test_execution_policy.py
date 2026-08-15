"""Integration tests for policy enforcement through the real API.

`test_policy.py` proves the decision logic. These prove it is actually wired in
— that a denied job does not reach the database, that the denial is audited, and
crucially that the check runs again at claim time. A policy engine that is
correct but only consulted at creation would leave the testing window advisory.
"""
import pytest

from db import SessionLocal
from models import AuditLog, Authorization, Engagement, ReconItem, ScanJob


@pytest.fixture
def engagement(client, auth_headers):
    """A bounty engagement with acme.com in scope — the default-allow baseline."""
    res = client.post("/programs", json={"name": "Policy Test"}, headers=auth_headers)
    pid = res.json()["id"]
    for value in ("acme.com", "*.acme.com"):
        res = client.post(
            f"/programs/{pid}/scope/in",
            json={"value": value, "kind": "domain"},
            headers=auth_headers,
        )
        assert res.status_code in (200, 201), res.text
    yield pid
    client.delete(f"/programs/{pid}", headers=auth_headers)


def _set(pid: str, **fields):
    """Set engagement columns the API deliberately does not expose (stop-work)."""
    db = SessionLocal()
    try:
        row = db.query(Engagement).filter(Engagement.id == pid).first()
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()
    finally:
        db.close()


def _add_authorization(pid: str, **fields):
    db = SessionLocal()
    try:
        db.add(Authorization(program_id=pid, owner_github_id="1", **fields))
        db.commit()
    finally:
        db.close()


def _denials(pid: str):
    db = SessionLocal()
    try:
        return (
            db.query(AuditLog)
            .filter(AuditLog.program_id == pid, AuditLog.action == "deny")
            .all()
        )
    finally:
        db.close()


def _job_count(pid: str) -> int:
    db = SessionLocal()
    try:
        return db.query(ScanJob).filter(ScanJob.program_id == pid).count()
    finally:
        db.close()


def _create_job(client, headers, pid, tool="httpx"):
    return client.post(
        f"/programs/{pid}/jobs",
        json={"tool_type": tool, "target_source": "scope"},
        headers=headers,
    )


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #

def test_in_scope_job_is_allowed(client, auth_headers, engagement):
    assert _create_job(client, auth_headers, engagement).status_code == 200


def test_stop_work_blocks_job_creation(client, auth_headers, engagement):
    from datetime import datetime, timezone

    _set(engagement, stop_work_at=datetime.now(timezone.utc), stop_work_reason="client call")
    res = _create_job(client, auth_headers, engagement)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "stop_work_active"


def test_denied_job_is_not_persisted(client, auth_headers, engagement):
    """A refused job must leave no queue entry behind."""
    from datetime import datetime, timezone

    before = _job_count(engagement)
    _set(engagement, stop_work_at=datetime.now(timezone.utc))
    assert _create_job(client, auth_headers, engagement).status_code == 403
    assert _job_count(engagement) == before


def test_denial_is_written_to_the_audit_log(client, auth_headers, engagement):
    from datetime import datetime, timezone

    _set(engagement, stop_work_at=datetime.now(timezone.utc))
    _create_job(client, auth_headers, engagement)

    denials = _denials(engagement)
    assert len(denials) == 1
    assert denials[0].reason == "stop_work_active"
    assert denials[0].resource_type == "execution"
    assert denials[0].detail  # the human-readable explanation is kept too


def test_closed_engagement_blocks_creation(client, auth_headers, engagement):
    _set(engagement, engagement_status="closed")
    res = _create_job(client, auth_headers, engagement)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "engagement_not_active"


def test_pentest_without_authorization_is_denied(client, auth_headers, engagement):
    """The gap this slice closes: authority was recorded but never enforced."""
    _set(engagement, engagement_type="pentest")
    res = _create_job(client, auth_headers, engagement)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "authorization_missing"


def test_pentest_with_active_authorization_is_allowed(client, auth_headers, engagement):
    _set(engagement, engagement_type="pentest")
    _add_authorization(engagement, status="active")
    assert _create_job(client, auth_headers, engagement).status_code == 200


def test_expired_testing_window_blocks_creation(client, auth_headers, engagement):
    from datetime import datetime, timedelta, timezone

    _set(engagement, engagement_type="pentest")
    _add_authorization(
        engagement,
        status="active",
        window_start=datetime.now(timezone.utc) - timedelta(days=2),
        window_end=datetime.now(timezone.utc) - timedelta(days=1),
    )
    res = _create_job(client, auth_headers, engagement)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "outside_testing_window"


def _add_recon(pid: str, host: str):
    db = SessionLocal()
    try:
        db.add(ReconItem(program_id=pid, source="httpx", host=host, url=f"https://{host}"))
        db.commit()
    finally:
        db.close()


def test_recon_sourced_job_is_denied_when_a_recon_host_is_out_of_scope(
    client, auth_headers, engagement
):
    """The case the control actually exists for.

    Recon discovers hosts; scope is narrowed afterwards. A job sourced from
    recon would otherwise happily scan a host that is no longer authorized.
    """
    _add_recon(engagement, "api.acme.com")
    _add_recon(engagement, "leaked.example.net")

    res = client.post(
        f"/programs/{engagement}/jobs",
        json={"tool_type": "httpx", "target_source": "recon"},
        headers=auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "target_out_of_scope"


def test_recon_sourced_job_is_allowed_when_every_host_is_in_scope(
    client, auth_headers, engagement
):
    _add_recon(engagement, "api.acme.com")
    _add_recon(engagement, "www.acme.com")

    res = client.post(
        f"/programs/{engagement}/jobs",
        json={"tool_type": "httpx", "target_source": "recon"},
        headers=auth_headers,
    )
    assert res.status_code == 200


def test_job_on_an_engagement_without_scope_is_allowed(client, auth_headers):
    """Zero targets executes nothing — refusing it would prevent nothing."""
    res = client.post("/programs", json={"name": "No Scope"}, headers=auth_headers)
    pid = res.json()["id"]
    try:
        assert _create_job(client, auth_headers, pid).status_code == 200
    finally:
        client.delete(f"/programs/{pid}", headers=auth_headers)


def test_engagement_gates_still_apply_without_scope(client, auth_headers):
    """...but stop-work must still refuse it."""
    from datetime import datetime, timezone

    res = client.post("/programs", json={"name": "No Scope Stopped"}, headers=auth_headers)
    pid = res.json()["id"]
    try:
        _set(pid, stop_work_at=datetime.now(timezone.utc))
        denied = _create_job(client, auth_headers, pid)
        assert denied.status_code == 403
        assert denied.json()["detail"]["reason"] == "stop_work_active"
    finally:
        client.delete(f"/programs/{pid}", headers=auth_headers)


def test_excluded_target_denies_even_with_matching_include(client, auth_headers, engagement):
    client.post(
        f"/programs/{engagement}/scope/out",
        json={"value": "acme.com", "kind": "domain"},
        headers=auth_headers,
    )
    res = _create_job(client, auth_headers, engagement)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "target_excluded"


# --------------------------------------------------------------------------- #
# Claim — the second enforcement point
# --------------------------------------------------------------------------- #

def test_claim_is_denied_when_stop_work_engaged_after_creation(
    client, auth_headers, engagement
):
    """The test that proves the evaluator is real rather than decorative.

    The job was legitimately queued. Stop-work is engaged afterwards. Claiming
    must fail — otherwise the emergency brake only applies to future jobs.
    """
    from datetime import datetime, timezone

    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    _set(engagement, stop_work_at=datetime.now(timezone.utc))

    res = client.post(f"/jobs/{job_id}/claim", headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "stop_work_active"


def test_job_stays_pending_after_a_denied_claim(client, auth_headers, engagement):
    """A refused claim must not consume the job."""
    from datetime import datetime, timezone

    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    _set(engagement, stop_work_at=datetime.now(timezone.utc))
    client.post(f"/jobs/{job_id}/claim", headers=auth_headers)

    db = SessionLocal()
    try:
        assert db.query(ScanJob).filter(ScanJob.id == job_id).first().status == "pending"
    finally:
        db.close()


def test_claim_is_denied_when_window_closes_after_creation(client, auth_headers, engagement):
    """Queued inside the window, claimed after it closed."""
    from datetime import datetime, timedelta, timezone

    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    _set(engagement, engagement_type="pentest")
    _add_authorization(
        engagement,
        status="active",
        window_end=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    res = client.post(f"/jobs/{job_id}/claim", headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "outside_testing_window"


def test_claim_is_denied_when_scope_is_revoked_after_creation(
    client, auth_headers, engagement
):
    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    client.post(
        f"/programs/{engagement}/scope/out",
        json={"value": "acme.com", "kind": "domain"},
        headers=auth_headers,
    )
    res = client.post(f"/jobs/{job_id}/claim", headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "target_excluded"


def test_claim_succeeds_when_policy_still_permits(client, auth_headers, engagement):
    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    assert client.post(f"/jobs/{job_id}/claim", headers=auth_headers).status_code == 200


def test_second_claim_still_returns_409_not_403(client, auth_headers, engagement):
    """Policy enforcement must not disturb the existing claim race semantics."""
    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    assert client.post(f"/jobs/{job_id}/claim", headers=auth_headers).status_code == 200
    assert client.post(f"/jobs/{job_id}/claim", headers=auth_headers).status_code == 409


def test_claiming_another_users_job_is_still_404(client, other_headers, engagement, auth_headers):
    """Cross-user access must stay 404 — never reveal that the job exists."""
    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    assert client.post(f"/jobs/{job_id}/claim", headers=other_headers).status_code == 404


# --------------------------------------------------------------------------- #
# Stop-work API — the brake must be operable from the product
# --------------------------------------------------------------------------- #

def test_stop_work_can_be_engaged_and_released(client, auth_headers, engagement):
    engaged = client.post(
        f"/programs/{engagement}/stop-work",
        json={"reason": "client called"},
        headers=auth_headers,
    )
    assert engaged.status_code == 200
    assert engaged.json()["stop_work_at"]
    assert engaged.json()["stop_work_reason"] == "client called"
    assert _create_job(client, auth_headers, engagement).status_code == 403

    released = client.delete(f"/programs/{engagement}/stop-work", headers=auth_headers)
    assert released.status_code == 200
    assert not released.json()["stop_work_at"]
    assert _create_job(client, auth_headers, engagement).status_code == 200


def test_engaging_stop_work_twice_is_idempotent(client, auth_headers, engagement):
    """During an incident the operator needs certainty, not an argument."""
    first = client.post(f"/programs/{engagement}/stop-work", json={}, headers=auth_headers)
    second = client.post(f"/programs/{engagement}/stop-work", json={}, headers=auth_headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["stop_work_at"] == second.json()["stop_work_at"]


def test_stop_work_is_audited(client, auth_headers, engagement):
    client.post(f"/programs/{engagement}/stop-work", json={"reason": "x"}, headers=auth_headers)
    db = SessionLocal()
    try:
        actions = [
            a.action
            for a in db.query(AuditLog).filter(AuditLog.program_id == engagement).all()
        ]
    finally:
        db.close()
    assert "stop_work" in actions


def test_stop_work_reason_is_sanitized(client, auth_headers, engagement):
    res = client.post(
        f"/programs/{engagement}/stop-work",
        json={"reason": "<script>alert(1)</script>incident"},
        headers=auth_headers,
    )
    assert "<script>" not in res.json()["stop_work_reason"]


def test_non_member_cannot_engage_stop_work(client, other_headers, engagement):
    """Cross-user access stays 404 — never confirm the engagement exists."""
    res = client.post(f"/programs/{engagement}/stop-work", json={}, headers=other_headers)
    assert res.status_code == 404


# --------------------------------------------------------------------------- #
# Regression — PATCH as an alternate route into execution
# --------------------------------------------------------------------------- #

def test_patch_to_running_is_denied_when_stop_work_is_engaged(
    client, auth_headers, engagement
):
    """Reported bypass: PATCH /jobs/{id} set status directly.

    A job denied at /claim could simply be PATCHed to running instead, which
    made the testing window, stop-work switch and scope rules advisory on that
    path. Both routes into `running` must clear the policy engine.
    """
    from datetime import datetime, timezone

    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    _set(engagement, stop_work_at=datetime.now(timezone.utc))

    res = client.patch(f"/jobs/{job_id}", json={"status": "running"}, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "stop_work_active"


def test_patch_to_running_is_denied_outside_the_testing_window(
    client, auth_headers, engagement
):
    from datetime import datetime, timedelta, timezone

    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    _set(engagement, engagement_type="pentest")
    _add_authorization(
        engagement, status="active", window_end=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    res = client.patch(f"/jobs/{job_id}", json={"status": "running"}, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "outside_testing_window"


def test_patch_job_stays_pending_after_a_denied_transition(client, auth_headers, engagement):
    from datetime import datetime, timezone

    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    _set(engagement, stop_work_at=datetime.now(timezone.utc))
    client.patch(f"/jobs/{job_id}", json={"status": "running"}, headers=auth_headers)

    db = SessionLocal()
    try:
        assert db.query(ScanJob).filter(ScanJob.id == job_id).first().status == "pending"
    finally:
        db.close()


def test_patch_to_running_still_works_when_policy_permits(client, auth_headers, engagement):
    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    res = client.patch(f"/jobs/{job_id}", json={"status": "running"}, headers=auth_headers)
    assert res.status_code == 200


def test_patch_to_terminal_states_is_not_policy_gated(client, auth_headers, engagement):
    """Completing or failing a job must never be blocked — a runner has to be
    able to report the outcome of work already done, even after a stop-work."""
    from datetime import datetime, timezone

    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    client.patch(f"/jobs/{job_id}", json={"status": "running"}, headers=auth_headers)
    _set(engagement, stop_work_at=datetime.now(timezone.utc))

    res = client.patch(f"/jobs/{job_id}", json={"status": "failed"}, headers=auth_headers)
    assert res.status_code == 200
