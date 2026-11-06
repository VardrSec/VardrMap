"""Real bounded ASGI sequence/retirement protocol; no execution or native proof."""

import hashlib
import json
from datetime import timedelta

import pytest
from managed_observation_http import build_observation_router
from managed_observations import Observations
from managed_runtime import BINDING_FIELDS
from managed_wire import digest
from models import (
    Engagement,
    JobExecution,
    ManagedApproval,
    ManagedContract,
    ManagedEnrollment,
    ManagedRuntime,
    ManagedRuntimeAttempt,
    ManagedStop,
    ScanJob,
)
from sqlalchemy import null
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests import test_managed_runtime_http as m
from tests.test_managed_runtime_http import http as http
from tests.test_managed_runtime_http import runtime_http as runtime_http
from tests.test_managed_issuance import signed
from tests.test_managed_issuance import specimen as specimen


@pytest.fixture
def sequence(http):
    h = http
    h.registration["max_attempts"] = 2
    h.app.include_router(build_observation_router(Observations(h.results)))
    return h


def claim(h, job="job-1", seq=1):
    response = h.client.post(
        f"/jobs/{job}/managed/claim",
        json={
            **h.body,
            "runtime_id": m.RUNTIME_ID,
            "runtime_sha256": h.sha,
            "runtime_sequence": seq,
        },
        headers=h.headers,
    )
    assert response.status_code == 200, response.text
    with Session(h.s["engine"]) as db:
        c = db.query(ManagedContract).filter_by(job_id=job).one()
        h.owned = {
            **h.pending,
            "token": response.json()["execution_control"]["token"],
            "contract_id": c.id,
            "attempt_id": c.attempt_id,
            "fence": c.fence,
            "contract_sha256": digest(c.envelope),
        }
    h.job, h.seq = job, seq
    return response.json()


def post(h, operation, body):
    return h.client.post(
        f"/jobs/{h.job}/managed/{operation}", json=body, headers=h.headers
    )


def confirm(h):
    assert post(h, "consume", h.owned).status_code == 200
    response = post(
        h,
        "runtime-bind",
        {
            **h.owned,
            "runtime_id": m.RUNTIME_ID,
            "runtime_sha256": h.sha,
            "runtime_sequence": h.seq,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["schema"] == "vardr.worker-runtime-binding/2"
    return response.json()


def complete(h, outcome="completed", *, finish=True):
    raw = {
        "test_case_id": h.s["review"]["case"]["id"],
        "case_hash": h.s["plan"]["case_hash"],
        "executions": [
            {"identity_id": "owner", "status_code": 200, "observed_outcome": "allow"}
        ],
        "findings": [],
    }
    text = json.dumps(raw)
    accepted = post(
        h,
        "result",
        {
            **h.owned,
            "artifact": text,
            "artifact_sha256": hashlib.sha256(text.encode()).hexdigest(),
        },
    )
    assert accepted.status_code == 200, accepted.text
    if not finish:
        return accepted.json()
    response = post(
        h,
        "finish",
        {
            **h.owned,
            "receipt_sha256": accepted.json()["receipt_sha256"],
            "outcome": outcome,
            "termination_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def release_body(h, terminal):
    return {
        **h.owned,
        "runtime_id": m.RUNTIME_ID,
        "runtime_sha256": h.sha,
        "runtime_sequence": h.seq,
        "terminal_receipt_sha256": digest(terminal),
        "native_done_sha256": "5" * 64,
    }


def next_job(h, job="job-2"):
    with Session(h.s["engine"]) as db:
        db.add(
            ScanJob(
                id=job,
                program_id="eng-1",
                owner_github_id="owner-1",
                tool_type="vardrgate_api_test",
                target_source="scope",
                authorization_contract_required=True,
                config={"test_case_id": "case-1"},
            )
        )
        db.commit()
    with Session(h.s["engine"]) as db:
        context = h.s["review"]["context"]
        review = h.s["service"].review(
            db,
            h.s["owner"],
            job_id=job,
            enrollment_id="enrollment-1",
            authorization_id="auth-1",
            plan=h.s["plan"],
            **{
                key: context[key]
                for key in (
                    "expires_at",
                    "max_executions",
                    "max_duration_seconds",
                    "max_artifact_bytes",
                    "credential_grants",
                )
            },
        )
        h.s["service"].register(
            db,
            h.s["owner"],
            job_id=job,
            enrollment_id="enrollment-1",
            authorization_id="auth-1",
            plan=h.s["plan"],
            approval=signed(review["context"], job),
        )


def exit_body(h, *, idle=False, sequence=None):
    common = {
        "runtime_sha256": h.sha,
        "finished_at": "2026-11-02T18:00:01Z",
        "exit_code": 0,
        "observation_sha256": "4" * 64,
    }
    if idle:
        return {**common, "last_sequence": h.seq if sequence is None else sequence}
    active = m.lookup(h).json()["active"]
    return {
        **common,
        **active["binding"],
        "runtime_sequence": active["runtime_sequence"],
    }


def observe(h, job="job-1", seq=1):
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
        "runtime_sequence": seq,
    }
    return h.client.post(
        f"/jobs/{job}/managed/observation", json=body, headers=h.headers
    )


def test_two_healthy_jobs_have_immutable_independent_history_and_nonrefundable_charges(
    sequence,
):
    h = sequence
    admission = m.register(h)
    assert (
        admission["schema"] == "vardr.worker-admission/2"
        and admission["max_attempts"] == 2
    )
    claim(h)
    first_binding = confirm(h)
    first_terminal = complete(h)
    next_job(h)
    # A completed job alone never opens the next runtime slot.
    assert (
        h.client.post(
            "/jobs/job-2/managed/claim",
            json={
                **h.body,
                "runtime_id": m.RUNTIME_ID,
                "runtime_sha256": h.sha,
                "runtime_sequence": 2,
            },
            headers=h.headers,
        ).status_code
        == 409
    )
    body = release_body(h, first_terminal)
    released = post(h, "runtime-idle-release", body)
    assert released.status_code == 200, released.text
    ack = released.json()
    assert ack["released"] is True and ack["receipt_sha256"] == digest(
        {k: v for k, v in ack.items() if k != "receipt_sha256"}
    )
    assert post(h, "runtime-idle-release", body).json() == ack
    old_exit = {
        "runtime_sha256": h.sha,
        **{k: first_binding[k] for k in BINDING_FIELDS},
        "runtime_sequence": 1,
        "finished_at": "2026-11-02T18:00:01Z",
        "exit_code": 137,
        "observation_sha256": "4" * 64,
    }
    claim(h, "job-2", 2)
    confirm(h)
    second_terminal = complete(h)
    assert m.post(h, "/observed-exit", old_exit).status_code == 409
    first = m.post(h, "/attempts/1/receipt", {"runtime_sha256": h.sha}).json()
    assert first["receipt"] == first_terminal and first["release"] == ack
    observed = observe(h)
    assert observed.status_code == 200, observed.text
    assert (
        observed.json()["completion"] == first_terminal
        and observed.json()["runtime_sequence"] == 1
    )
    released2 = post(h, "runtime-idle-release", release_body(h, second_terminal))
    assert released2.status_code == 200, released2.text
    next_job(h, "job-3")
    assert (
        h.client.post(
            "/jobs/job-3/managed/claim",
            json={
                **h.body,
                "runtime_id": m.RUNTIME_ID,
                "runtime_sha256": h.sha,
                "runtime_sequence": 3,
            },
            headers=h.headers,
        ).status_code
        == 409
    )
    # Final physical retirement is distinct from either successful job receipt.
    retired = m.post(h, "/observed-unbound-exit", exit_body(h, idle=True))
    assert retired.status_code == 200, retired.text
    final = retired.json()["receipt"]
    assert (
        final["schema"] == "vardr.worker-retirement/2" and final["last_sequence"] == 2
    )
    assert (
        final["runtime_sequence"]
        is final["binding"]
        is final["attempt_receipt"]
        is None
    )
    assert m.lookup(h).json()["retirement"] == final
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedRuntimeAttempt).count() == 2
        engagement = db.get(Engagement, "eng-1")
        assert (engagement.targets_spent, engagement.duration_allocated) == (2, 60)
        assert db.query(ManagedStop).count() == 0


@pytest.mark.parametrize("invalid", [None, True, 0, 33, 1.0, "2"])
def test_explicit_bound_and_sequence_are_strict_and_never_fallback(sequence, invalid):
    h = sequence
    assert (
        m.post(
            h, "/register", {**h.registration, "max_attempts": invalid}, h.owner
        ).status_code
        == 422
    )
    m.register(h)
    assert (
        h.client.post(
            "/jobs/job-1/managed/claim",
            json={
                **h.body,
                "runtime_id": m.RUNTIME_ID,
                "runtime_sha256": h.sha,
                "runtime_sequence": invalid,
            },
            headers=h.headers,
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "change",
    [
        "terminal_hash",
        "done_hash",
        "unconfirmed",
        "failed",
        "cancelled",
        "revoked",
        "expired",
        "wrong_key",
    ],
)
def test_only_exact_confirmed_healthy_completion_releases_with_active_grant(
    sequence, change
):
    h = sequence
    m.register(h)
    claim(h)
    if change == "unconfirmed":
        m.consume(h)
    else:
        confirm(h)
    terminal = complete(h, change if change in {"failed", "cancelled"} else "completed")
    body = release_body(h, terminal)
    if change == "terminal_hash":
        body["terminal_receipt_sha256"] = terminal["receipt_sha256"]
    elif change == "done_hash":
        body["native_done_sha256"] = "invalid"
    elif change == "revoked":
        assert m.post(h, "/revoke", {}, h.owner).status_code == 200
    elif change == "expired":
        h.s["wall"][0] += timedelta(seconds=3601)
    headers = (
        {"Authorization": "Bearer vmap_invalid"} if change == "wrong_key" else h.headers
    )
    result = h.client.post(
        "/jobs/job-1/managed/runtime-idle-release", json=body, headers=headers
    )
    assert result.status_code in {401, 409, 422}
    with Session(h.s["engine"]) as db:
        assert db.get(ManagedRuntime, m.RUNTIME_ID).active_sequence == 1
        assert db.query(ManagedRuntimeAttempt).one().released_at is None


def test_idle_epoch_and_historical_receipts_never_retire_a_later_attempt(sequence):
    h = sequence
    m.register(h)
    claim(h)
    confirm(h)
    terminal = complete(h)
    assert post(h, "runtime-idle-release", release_body(h, terminal)).status_code == 200
    old_idle = exit_body(h, idle=True)
    next_job(h)
    claim(h, "job-2", 2)
    assert m.post(h, "/observed-unbound-exit", old_idle).status_code == 409
    # Physical exit before consume retires the exact second attempt, no fake ACK.
    retired = m.post(h, "/observed-exit", exit_body(h))
    assert retired.status_code == 200, retired.text
    r = retired.json()["receipt"]
    assert r["runtime_sequence"] == r["last_sequence"] == 2
    assert r["attempt_receipt"]["cause"] == "observed_exit"
    observed = observe(h, "job-2", 2)
    assert observed.status_code == 200, observed.text
    assert observed.json()["claim"]["consumed"] is False
    assert observed.json()["execution_state"] == "failed"
    assert observe(h).json()["completion"] == terminal
    assert observe(h, "job-1", 2).status_code == 409
    h.s["wall"][0] += timedelta(seconds=3601)
    assert m.lookup(h).json()["retirement"] == r
    assert (
        m.post(h, "/attempts/1/receipt", {"runtime_sha256": h.sha}).json()["receipt"]
        == terminal
    )


def test_final_idle_retirement_proves_only_never_issued_sequence_and_requires_original_key(
    sequence,
):
    h = sequence
    m.register(h)
    h.seq = 0
    retired = m.post(h, "/observed-unbound-exit", exit_body(h, idle=True))
    assert retired.status_code == 200, retired.text
    response = observe(h)
    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply["schema"] == "vardr.managed-claim-observation/3"
    assert reply["runtime_id"] == m.RUNTIME_ID and reply["runtime_sha256"] == h.sha
    assert reply["runtime_sequence"] == 1 and reply["claim"] is None
    assert reply["runtime_retirement"] == retired.json()["receipt"]
    assert (
        h.client.post(
            "/jobs/job-1/managed/claim",
            json={
                **h.body,
                "runtime_id": m.RUNTIME_ID,
                "runtime_sha256": h.sha,
                "runtime_sequence": 1,
            },
            headers=h.headers,
        ).status_code
        == 409
    )
    with Session(h.s["engine"]) as db:
        row = db.get(ManagedEnrollment, "enrollment-1")
        row.revoked, row.revision = True, row.revision + 1
        db.commit()
    assert observe(h).status_code == 409
    assert m.lookup(h).json()["retirement"] == retired.json()["receipt"]


@pytest.mark.parametrize(
    "corruption", ["missing_history", "counter", "partial_release"]
)
def test_incomplete_history_never_looks_like_unclaimed_or_idle(sequence, corruption):
    h = sequence
    m.register(h)
    claim(h)
    with Session(h.s["engine"]) as db:
        row = db.query(ManagedRuntimeAttempt).one()
        if corruption == "missing_history":
            db.delete(row)
        elif corruption == "counter":
            db.get(ManagedRuntime, m.RUNTIME_ID).last_sequence = 0
        else:
            row.native_done_sha256 = "5" * 64
        db.commit()
    assert m.lookup(h).status_code == 409
    assert observe(h).status_code == 409


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_physical_retirement_preserves_existing_terminal_without_rewriting_job(
    sequence, outcome
):
    h = sequence
    m.register(h)
    claim(h)
    confirm(h)
    terminal = complete(h, outcome)
    accepted = m.post(h, "/observed-exit", exit_body(h))
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()["receipt"]
    assert receipt["attempt_receipt"] == terminal
    assert receipt["receipt_sha256"] == digest(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    assert m.post(h, "/observed-exit", exit_body(h)).json() == accepted.json()
    assert post(h, "runtime-idle-release", release_body(h, terminal)).status_code == 409
    assert (
        m.post(h, "/attempts/1/receipt", {"runtime_sha256": h.sha}).json()["receipt"]
        == terminal
    )
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedStop).count() == 0
        assert db.get(ScanJob, "job-1").status == (
            "done" if outcome == "completed" else "failed"
        )


def test_protocol_version_cannot_upgrade_or_downgrade_an_existing_incarnation(sequence):
    h = sequence
    h.registration["max_attempts"] = 1
    first = m.register(h)
    assert first["schema"] == "vardr.worker-admission/2" and first["max_attempts"] == 1
    assert (
        m.post(
            h, "/register", {**h.registration, "max_attempts": 2}, h.owner
        ).status_code
        == 409
    )
    legacy = {
        key: value for key, value in h.registration.items() if key != "max_attempts"
    }
    assert m.post(h, "/register", legacy, h.owner).status_code == 409
    assert (
        h.client.post(
            "/jobs/job-1/managed/claim",
            json={**h.body, "runtime_id": m.RUNTIME_ID, "runtime_sha256": h.sha},
            headers=h.headers,
        ).status_code
        == 409
    )
    # A legacy /2 observation cannot invent a multi-attempt retirement shape.
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
    }
    assert (
        h.client.post(
            "/jobs/job-1/managed/observation", json=body, headers=h.headers
        ).status_code
        == 409
    )


@pytest.mark.parametrize("headers", [None, "owner", "key", "wrong_stop"])
def test_history_lookup_requires_only_the_exact_separate_host_capability(
    sequence, headers
):
    h = sequence
    m.register(h)
    claim(h)
    selected = {
        None: {},
        "owner": h.owner,
        "key": h.headers,
        "wrong_stop": {"Authorization": "VardrStop " + "f" * 64},
    }[headers]
    response = m.post(h, "/attempts/1/receipt", {"runtime_sha256": h.sha}, selected)
    assert response.status_code == 404 and response.json() == {
        "detail": "managed_runtime_refused"
    }


def test_physical_exit_fails_pending_result_without_creating_another_receipt(sequence):
    h = sequence
    m.register(h)
    claim(h)
    confirm(h)
    accepted = complete(h, finish=False)
    response = m.post(h, "/observed-exit", exit_body(h))
    assert response.status_code == 200, response.text
    completion = response.json()["receipt"]["attempt_receipt"]
    assert completion["outcome"] == "failed"
    assert completion["receipt_sha256"] == accepted["receipt_sha256"]
    assert observe(h).json()["result"] == accepted
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedStop).count() == 0
        assert db.query(ManagedRuntimeAttempt).count() == 1
        engagement = db.get(Engagement, "eng-1")
        assert (engagement.targets_spent, engagement.duration_allocated) == (1, 30)


def test_other_runtime_or_orphan_history_never_proves_a_pending_job_unclaimed(sequence):
    h = sequence
    m.register(h)
    h.seq = 0
    assert (
        m.post(h, "/observed-unbound-exit", exit_body(h, idle=True)).status_code == 200
    )
    with Session(h.s["engine"]) as db:
        db.add(
            ManagedRuntimeAttempt(
                runtime_id="orphan-runtime",
                runtime_sequence=1,
                job_id="job-1",
                contract_id="00000000-0000-0000-0000-000000000021",
                attempt_id="00000000-0000-0000-0000-000000000022",
                fence=1,
                contract_sha256="4" * 64,
                bound_at=h.s["wall"][0].replace(tzinfo=None),
            )
        )
        db.commit()
    assert observe(h).status_code == 409


def test_database_backstop_rolls_back_an_old_style_claim_and_all_spend(sequence):
    h = sequence
    m.register(h)

    def old_prepare(*, db, now, job, approval, projection):
        row = (
            db.query(ManagedRuntime).filter_by(id=m.RUNTIME_ID).with_for_update().one()
        )

        def associate(contract):
            row.job_id, row.contract_id, row.attempt_id = (
                job.id,
                contract.id,
                contract.attempt_id,
            )
            row.fence, row.contract_sha256 = contract.fence, digest(contract.envelope)
            row.bound_at = now().replace(tzinfo=None)
            db.flush()

        return associate

    with Session(h.s["engine"]) as db:
        with pytest.raises(IntegrityError):
            h.s["service"].claim(
                db,
                h.s["runner"],
                job_id="job-1",
                body=h.s["body"],
                on_claim=old_prepare,
            )
    with Session(h.s["engine"]) as db:
        assert db.get(ScanJob, "job-1").status == "pending"
        assert db.query(ManagedContract).count() == db.query(JobExecution).count() == 0
        assert db.query(ManagedRuntimeAttempt).count() == 0
        engagement = db.get(Engagement, "eng-1")
        assert (engagement.targets_spent, engagement.duration_allocated) == (0, 0)
        assert db.query(ManagedApproval).one().issued == 0


@pytest.mark.parametrize("json_null", [False, True])
def test_database_backstop_refuses_old_style_retirement_without_physical_receipt(
    sequence, json_null
):
    h = sequence
    m.register(h)
    with Session(h.s["engine"]) as db:
        row = db.get(ManagedRuntime, m.RUNTIME_ID)
        row.retired, row.report_sha256 = True, "4" * 64
        row.retirement_receipt = None if json_null else null()
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        assert db.get(ManagedRuntime, m.RUNTIME_ID).retired is False
