"""Inactive persistent ASGI protocol; no Docker, native control or target calls."""

import copy
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from managed_observation_http import build_observation_router
from managed_observations import Observations
from managed_persistent_wire import MAX_SEQUENCE, sequence
from managed_wire import WireRefused, digest
from models import (
    Engagement,
    JobExecution,
    ManagedContract,
    ManagedEnrollment,
    ManagedRuntime,
    ManagedRuntimeAttempt,
    ManagedStop,
)
from tests import test_managed_runtime_http as m
from tests import test_managed_runtime_sequence as finite
from tests.test_managed_runtime_http import http as http
from tests.test_managed_runtime_http import runtime_http as runtime_http
from tests.test_managed_issuance import specimen as specimen


@pytest.fixture
def persistent(http):
    h = http
    # Explicit isolated injection. Production configuration does not pass True.
    h.runtimes.persistent_enabled = True
    h.app.include_router(build_observation_router(Observations(h.results)))
    event.listen(
        h.s["engine"],
        "connect",
        lambda dbapi, _: dbapi.execute("PRAGMA foreign_keys=ON"),
    )
    h.s["engine"].dispose()
    with h.s["engine"].connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    h.registration.pop("expires_in_seconds")
    h.registration.update(
        mode="persistent",
        limits={"max_attempts": None, "idle_timeout_seconds": None},
        reporting_authority={"purpose": "worker-stop-only", "expires_at": None},
    )
    return h


def register(h):
    admission = m.register(h)
    h.admission_sha = admission["admission_sha256"]
    return admission


def lookup(h, suffix="/receipt", **body):
    return m.post(
        h,
        suffix,
        {"runtime_sha256": h.sha, "admission_sha256": h.admission_sha, **body},
    )


def claim(h, job="job-1", seq="1"):
    response = h.client.post(
        f"/jobs/{job}/managed/claim",
        json={
            **h.body,
            "runtime_id": m.RUNTIME_ID,
            "runtime_sha256": h.sha,
            "admission_sha256": h.admission_sha,
            "runtime_sequence": seq,
        },
        headers=h.headers,
    )
    assert response.status_code == 200, response.text
    with Session(h.s["engine"]) as db:
        contract = db.query(ManagedContract).filter_by(job_id=job).one()
        h.owned = {
            **h.pending,
            "token": response.json()["execution_control"]["token"],
            "contract_id": contract.id,
            "attempt_id": contract.attempt_id,
            "fence": contract.fence,
            "contract_sha256": digest(contract.envelope),
        }
    h.job, h.seq = job, seq
    return response.json()


def bound(h):
    return {
        **h.owned,
        "runtime_id": m.RUNTIME_ID,
        "runtime_sha256": h.sha,
        "admission_sha256": h.admission_sha,
        "runtime_sequence": h.seq,
    }


def confirm(h):
    assert finite.post(h, "consume", h.owned).status_code == 200
    response = finite.post(h, "runtime-bind", bound(h))
    assert response.status_code == 200, response.text
    assert response.json()["schema"] == "vardr.worker-runtime-binding/3"
    return response.json()


def release(h, terminal):
    return finite.post(
        h,
        "runtime-idle-release",
        {
            **bound(h),
            "terminal_receipt_sha256": digest(terminal),
            "native_done_sha256": "5" * 64,
        },
    )


@pytest.mark.parametrize("value", ["0", "1", str(2**53 + 1), str(MAX_SEQUENCE)])
def test_counter_keeps_exact_signed64_decimal(value):
    assert sequence(value) == int(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        1,
        1.0,
        "",
        "+1",
        "-1",
        "01",
        "1.0",
        "1e1",
        "١",
        str(MAX_SEQUENCE + 1),
    ],
)
def test_counter_refuses_ambiguous_or_overflowed_values(value):
    with pytest.raises(WireRefused):
        sequence(value)


def test_persistent_admission_is_inactive_by_default_and_immutable(persistent):
    h = persistent
    h.runtimes.persistent_enabled = False
    assert m.post(h, "/register", h.registration, h.owner).status_code == 409
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedRuntime).count() == 0
    h.runtimes.persistent_enabled = True
    admission = register(h)
    assert (
        admission["schema"] == "vardr.worker-admission/3"
        and "expires_at" not in admission
    )
    assert (
        admission["mode"] == "persistent"
        and admission["limits"] == h.registration["limits"]
    )
    assert admission["reporting_authority"] == h.registration["reporting_authority"]
    assert (
        digest({k: v for k, v in admission.items() if k != "admission_sha256"})
        == h.admission_sha
    )
    assert m.post(h, "/register", h.registration, h.owner).json() == admission
    changed = copy.deepcopy(h.registration)
    changed["limits"]["max_attempts"] = "32"
    assert m.post(h, "/register", changed, h.owner).status_code == 409
    with Session(h.s["engine"]) as db:
        row = db.get(ManagedRuntime, m.RUNTIME_ID)
        assert row.ttl_seconds is row.expires_at is None
        assert row.max_attempts is row.idle_timeout_seconds is None
        assert row.last_sequence == 0 and row.head_sequence is None


@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_known_terminal_releases_exact_slot_without_refund(persistent, outcome):
    h = persistent
    register(h)
    claim(h)
    confirm(h)
    terminal = finite.complete(h, outcome)
    accepted = release(h, terminal)
    assert accepted.status_code == 200, accepted.text
    ack = accepted.json()
    assert (
        ack["schema"] == "vardr.worker-idle-release/2"
        and ack["runtime_sequence"] == "1"
    )
    assert ack["admission_sha256"] == h.admission_sha and ack[
        "terminal_receipt_sha256"
    ] == digest(terminal)
    assert (
        digest({k: v for k, v in ack.items() if k != "receipt_sha256"})
        == ack["receipt_sha256"]
    )
    current = lookup(h).json()
    assert current["cursor"] == {"last_sequence": "1", "phase": "idle"}
    assert current["active"] is None
    history = lookup(h, "/attempts/1/receipt").json()
    assert history["schema"] == "vardr.worker-attempt-observation/2"
    assert history["receipt"] == terminal and history["release"] == ack
    with Session(h.s["engine"]) as db:
        eng = db.get(Engagement, "eng-1")
        assert (eng.targets_spent, eng.duration_allocated) == (1, 30)
        assert db.get(ManagedRuntime, m.RUNTIME_ID).head_sequence == 1
        assert db.query(ManagedStop).count() == 0


def test_discovery_excludes_stopped_and_stale_approved_jobs(persistent):
    from routers import engagements

    h = persistent
    register(h)
    runtime = {
        "runtime_id": m.RUNTIME_ID,
        "runtime_sha256": h.sha,
        "admission_sha256": h.admission_sha,
    }
    pending = {**h.pending, **runtime, "cursor": {"last_sequence": "0", "phase": "idle"}}

    def jobs():
        response = h.client.post("/jobs/managed/pending", json=pending, headers=h.headers)
        assert response.status_code == 200
        assert response.json()["availability"]["state"] == "idle-ready"
        return [job["id"] for job in response.json()["jobs"]]

    assert jobs() == ["job-1"]
    before = m.state(h)
    owner = {"github_id": "owner-1", "scope": "full"}
    with Session(h.s["engine"]) as db:
        engagements.engage_stop_work(
            "eng-1", engagements.StopWorkRequest(reason="synthetic"), owner, db
        )
    assert jobs() == []
    refused = h.client.post(
        "/jobs/job-1/managed/claim",
        json={**h.body, **runtime, "runtime_sequence": "1"},
        headers=h.headers,
    )
    assert refused.status_code == 409
    assert m.state(h) == before

    with Session(h.s["engine"]) as db:
        engagements.release_stop_work("eng-1", owner, db)
    assert jobs() == []
    assert m.state(h) == before


def test_presence_is_advisory_fresh_cursor_only_and_disable_preserves_reporting(
    persistent,
):
    h = persistent
    register(h)
    body = {
        **h.pending,
        "limit": 1,
        "runtime_id": m.RUNTIME_ID,
        "runtime_sha256": h.sha,
        "admission_sha256": h.admission_sha,
        "cursor": {"last_sequence": "0", "phase": "idle"},
    }
    response = h.client.post("/jobs/managed/pending", json=body, headers=h.headers)
    assert response.status_code == 200, response.text
    assert response.json()["availability"]["state"] == "idle-ready"
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedContract).count() == 0
        assert db.get(Engagement, "eng-1").targets_spent == 0
    h.s["wall"][0] += timedelta(seconds=16)
    assert lookup(h).json()["availability"]["state"] == "held"
    disabled = lookup(h, "/disable")
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["new_work_disabled"] is True
    current = lookup(h).json()
    assert current["new_work_disabled"] and current["reporting_revoked"] is False
    refused = h.client.post(
        "/jobs/job-1/managed/claim",
        json={
            **h.body,
            "runtime_id": m.RUNTIME_ID,
            "runtime_sha256": h.sha,
            "admission_sha256": h.admission_sha,
            "runtime_sequence": "1",
        },
        headers=h.headers,
    )
    assert refused.status_code == 409
    report = lookup(
        h,
        "/observed-unbound-exit",
        last_sequence="0",
        finished_at="2026-11-02T18:00:17Z",
        exit_code=0,
        observation_sha256="4" * 64,
    )
    assert report.status_code == 200, report.text
    assert report.json()["receipt"]["schema"] == "vardr.worker-retirement/3"
    assert lookup(h).json()["availability"]["state"] == "stopped"


def test_disable_new_work_keeps_bound_control_and_terminal_release(persistent):
    h = persistent
    register(h)
    claim(h)
    confirm(h)
    assert lookup(h, "/disable").status_code == 200
    response = finite.post(
        h, "refresh", {k: v for k, v in h.owned.items() if k != "contract_sha256"}
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["action"] == "continue"
        and 0 < response.json()["lease_seconds"] <= 10
    )
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").capacity_reserved is True
    assert release(h, finite.complete(h)).status_code == 200
    assert lookup(h).json()["availability"]["state"] == "held"
    finite.next_job(h)
    response = h.client.post(
        "/jobs/job-2/managed/claim",
        json={
            **h.body,
            "runtime_id": m.RUNTIME_ID,
            "runtime_sha256": h.sha,
            "admission_sha256": h.admission_sha,
            "runtime_sequence": "2",
        },
        headers=h.headers,
    )
    assert response.status_code == 409


def test_fk_chain_retains_head_and_predecessor_after_real_releases(persistent):
    h = persistent
    register(h)
    for n in range(1, 3):
        if n > 1:
            finite.next_job(h)
        claim(h, "job-1" if n == 1 else "job-2", str(n))
        confirm(h)
        assert release(h, finite.complete(h)).status_code == 200
    for number in (1, 2):
        with Session(h.s["engine"]) as db:
            db.execute(
                delete(ManagedRuntimeAttempt).where(
                    ManagedRuntimeAttempt.runtime_id == m.RUNTIME_ID,
                    ManagedRuntimeAttempt.runtime_sequence == number,
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    with Session(h.s["engine"]) as db:
        assert list(
            db.scalars(
                select(ManagedRuntimeAttempt.runtime_sequence).order_by(
                    ManagedRuntimeAttempt.runtime_sequence
                )
            )
        ) == [1, 2]
        assert db.get(ManagedRuntime, m.RUNTIME_ID).last_sequence == 2


def test_thirty_three_jobs_retain_all_history_with_exact_selected_reads(persistent):
    h = persistent
    register(h)
    # Explicit fixture budget increase, then fresh human approval per NEW job.
    # No existing approval or spending record is rewritten to fit a claim.
    with Session(h.s["engine"]) as db:
        engagement = db.get(Engagement, "eng-1")
        engagement.target_limit, engagement.duration_limit = 100, 10000
        db.commit()
    terminals = {}
    for n in range(1, 34):
        job = f"many-{n}"
        finite.next_job(h, job)
        claim(h, job, str(n))
        confirm(h)
        terminals[n] = finite.complete(h)
        accepted = release(h, terminals[n])
        assert accepted.status_code == 200, (n, accepted.text)
    statements = []

    def observed(connection, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "managed_runtime_attempts" in statement
        ):
            statements.append((statement, parameters))

    event.listen(h.s["engine"], "before_cursor_execute", observed)
    try:
        current = lookup(h).json()
        first = lookup(h, "/attempts/1/receipt").json()
        last = lookup(h, "/attempts/33/receipt").json()
    finally:
        event.remove(h.s["engine"], "before_cursor_execute", observed)
    assert current["cursor"] == {"last_sequence": "33", "phase": "idle"}
    assert first["receipt"] == terminals[1] and last["receipt"] == terminals[33]
    assert all(
        "WHERE" in statement and "LIMIT" in statement for statement, _ in statements
    )
    assert all(tuple(parameters)[-2:] == (1, 0) for _, parameters in statements)
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedRuntimeAttempt).count() == 33
        engagement = db.get(Engagement, "eng-1")
        assert (engagement.targets_spent, engagement.duration_allocated) == (33, 990)


def test_persistent_identity_survives_idle_but_never_extends_job_authority(persistent):
    h = persistent
    register(h)
    h.s["wall"][0] += timedelta(seconds=70)
    # The old approval expired at60s: persistent presence is not permission.
    denied = h.client.post(
        "/jobs/job-1/managed/claim",
        json={
            **h.body,
            "runtime_id": m.RUNTIME_ID,
            "runtime_sha256": h.sha,
            "admission_sha256": h.admission_sha,
            "runtime_sequence": "1",
        },
        headers=h.headers,
    )
    assert denied.status_code == 409
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedContract).count() == 0
        assert db.get(Engagement, "eng-1").targets_spent == 0
    # Create a separately reviewed, signed approval for a NEW job at the new time.
    h.s["review"]["context"]["expires_at"] = "2026-11-02T18:10:00Z"
    finite.next_job(h, "late-job")
    claim(h, "late-job", "1")
    confirm(h)
    assert release(h, finite.complete(h)).status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_attempts", 32),
        ("max_attempts", True),
        ("max_attempts", "032"),
        ("max_attempts", str(MAX_SEQUENCE + 1)),
        ("idle_timeout_seconds", True),
        ("idle_timeout_seconds", 0),
        ("idle_timeout_seconds", 86401),
    ],
)
def test_optional_limits_never_coerce_and_do_not_create_admission(
    persistent, field, value
):
    h = persistent
    body = copy.deepcopy(h.registration)
    body["limits"][field] = value
    assert m.post(h, "/register", body, h.owner).status_code == 422
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedRuntime).count() == 0


@pytest.mark.parametrize("policy", ["idle", "count"])
def test_explicit_finite_controls_are_optional_and_enforced_before_charge(
    persistent, policy
):
    h = persistent
    h.registration["limits"][
        "idle_timeout_seconds" if policy == "idle" else "max_attempts"
    ] = 1 if policy == "idle" else "1"
    register(h)
    if policy == "idle":
        h.s["wall"][0] += timedelta(seconds=2)
        job, number, charged = "job-1", "1", 0
    else:
        claim(h)
        confirm(h)
        assert release(h, finite.complete(h)).status_code == 200
        finite.next_job(h)
        job, number, charged = "job-2", "2", 1
    response = h.client.post(
        f"/jobs/{job}/managed/claim",
        json={
            **h.body,
            "runtime_id": m.RUNTIME_ID,
            "runtime_sha256": h.sha,
            "admission_sha256": h.admission_sha,
            "runtime_sequence": number,
        },
        headers=h.headers,
    )
    assert response.status_code == 409
    with Session(h.s["engine"]) as db:
        assert db.get(Engagement, "eng-1").targets_spent == charged
        assert db.query(ManagedContract).count() == charged


@pytest.mark.parametrize("legacy", ["v1", "v2"])
def test_old_runtime_requests_cannot_downgrade_persistent_admission(persistent, legacy):
    h = persistent
    register(h)
    body = {**h.body, "runtime_id": m.RUNTIME_ID, "runtime_sha256": h.sha}
    if legacy == "v2":
        body["runtime_sequence"] = 1
    assert (
        h.client.post(
            "/jobs/job-1/managed/claim", json=body, headers=h.headers
        ).status_code
        == 409
    )
    assert m.post(h, "/receipt", {"runtime_sha256": h.sha}).status_code == 409
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedContract).count() == 0
        assert db.get(Engagement, "eng-1").duration_allocated == 0


@pytest.mark.parametrize("kind", ["pending", "cancelled", "retired"])
def test_unknown_cancelled_or_physical_exit_cannot_release_for_reuse(persistent, kind):
    h = persistent
    register(h)
    claim(h)
    confirm(h)
    if kind == "pending":
        finite.complete(h, finish=False)
        terminal = {"unproven": True}
    else:
        terminal = finite.complete(h, "cancelled" if kind == "cancelled" else "failed")
    if kind == "retired":
        report = lookup(
            h,
            "/observed-exit",
            **lookup(h).json()["active"]["binding"],
            runtime_sequence="1",
            finished_at="2026-11-02T18:00:01Z",
            exit_code=0,
            observation_sha256="4" * 64,
        )
        assert report.status_code == 200, report.text
    assert release(h, terminal).status_code == 409
    assert lookup(h).json()["active"]["runtime_sequence"] == "1"


def observe(h, job="job-1", number="1", headers=None):
    body = {
        **h.pending,
        "plan_sha256": digest(h.s["plan"]),
        "case_sha256": h.s["plan"]["case_hash"],
        "association_sha256": digest(
            {
                "origin": m.runtime.ORIGIN,
                "runner_id": m.RUNNER,
                "principal_sha256": hashlib.sha256(
                    ("Bearer " + m.KEY).encode()
                ).hexdigest(),
            }
        ),
        "runtime_id": m.RUNTIME_ID,
        "runtime_sha256": h.sha,
        "admission_sha256": h.admission_sha,
        "runtime_sequence": number,
    }
    return h.client.post(
        f"/jobs/{job}/managed/observation",
        json=body,
        headers=h.headers if headers is None else headers,
    )


@pytest.mark.parametrize("claimed", [False, True])
def test_original_key_v4_retirement_never_fakes_consumption_or_claim(
    persistent, claimed
):
    h = persistent
    register(h)
    if claimed:
        claim(h)
        current = lookup(h).json()
        report = lookup(
            h,
            "/observed-exit",
            **current["active"]["binding"],
            runtime_sequence="1",
            finished_at="2026-11-02T18:00:01Z",
            exit_code=125,
            observation_sha256="4" * 64,
        )
    else:
        report = lookup(
            h,
            "/observed-unbound-exit",
            last_sequence="0",
            finished_at="2026-11-02T18:00:01Z",
            exit_code=125,
            observation_sha256="4" * 64,
        )
    assert report.status_code == 200, report.text
    response = observe(h)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["schema"] == "vardr.managed-claim-observation/4"
    assert (
        value["admission_sha256"] == h.admission_sha
        and value["runtime_sequence"] == "1"
    )
    assert value["runtime_retirement"] == report.json()["receipt"]
    if claimed:
        assert value["claim"]["consumed"] is False
        assert (
            value["stop"]["cause"] == "observed_exit"
            and value["capacity_reserved"] is False
        )
    else:
        assert value["claim"] is None and value["stop"] is None
    assert observe(h, headers=h.owner).status_code in {403, 404}
    with Session(h.s["engine"]) as db:
        enrollment = db.get(ManagedEnrollment, "enrollment-1")
        enrollment.revoked, enrollment.revision = True, enrollment.revision + 1
        db.commit()
    assert observe(h).status_code == 409


def test_inactive_graph_does_not_renew_existing_persistent_control(persistent):
    h = persistent
    register(h)
    claim(h)
    confirm(h)
    h.runtimes.persistent_enabled = False
    assert (
        finite.post(
            h, "refresh", {k: v for k, v in h.owned.items() if k != "contract_sha256"}
        ).status_code
        == 409
    )


def test_v3_registration_reuses_owner_auth_and_never_implicitly_enables(persistent):
    h = persistent
    assert m.post(h, "/register", h.registration, h.headers).status_code == 409
    assert (
        m.post(
            h, "/register", {**h.registration, "persistent_enabled": True}, h.owner
        ).status_code
        == 422
    )
    assert (
        m.post(
            h, "/register", {**h.registration, "expires_in_seconds": 3600}, h.owner
        ).status_code
        == 422
    )
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedRuntime).count() == 0


def test_stale_idle_presence_cannot_overwrite_active_cursor_or_refresh_permission(
    persistent,
):
    h = persistent
    register(h)
    idle = {
        **h.pending,
        "runtime_id": m.RUNTIME_ID,
        "runtime_sha256": h.sha,
        "admission_sha256": h.admission_sha,
        "cursor": {"last_sequence": "0", "phase": "idle"},
    }
    assert (
        h.client.post("/jobs/managed/pending", json=idle, headers=h.headers).status_code
        == 200
    )
    claim(h)
    confirm(h)
    with Session(h.s["engine"]) as db:
        before = db.get(JobExecution, "job-1").expires_at
    assert (
        h.client.post("/jobs/managed/pending", json=idle, headers=h.headers).status_code
        == 409
    )
    current = lookup(h).json()
    assert current["cursor"] == {"last_sequence": "1", "phase": "active"}
    assert current["availability"]["state"] == "active"
    assert current["availability"]["cursor"] == current["cursor"]
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == before


def test_missing_admission_hash_and_noncanonical_history_never_downgrade(persistent):
    h = persistent
    register(h)
    for bad in ("01", "+1", "0", str(MAX_SEQUENCE + 1)):
        assert lookup(h, f"/attempts/{bad}/receipt").status_code == 422
    assert lookup(h, f"/attempts/{2**53 + 1}/receipt").status_code == 409
    assert lookup(h, "/receipt", admission_sha256="0" * 64).status_code == 409
    assert m.post(h, "/disable", {"runtime_sha256": h.sha}).status_code == 422
