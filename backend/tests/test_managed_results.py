"""Owned managed result transactions in disposable databases."""

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import assessments
from managed_results import Results
from managed_wire import WireRefused
from models import (
    Engagement,
    Evidence,
    JobExecution,
    JobResultReceipt,
    ManagedApproval,
    ManagedContract,
    ManagedResult,
    ScanItem,
    ScanJob,
)
from tests.test_managed_consumption import consume
from tests.test_managed_consumption import consumption as consumption
from tests.test_managed_issuance import specimen as specimen


@pytest.fixture
def results(consumption):
    s, args = consumption
    consume(s, args)
    with Session(s["engine"]) as db:
        case = copy.deepcopy(db.get(ScanJob, "job-1").case_snapshot)
    raw = {
        "test_case_id": case["id"],
        "case_hash": assessments.case_hash(case),
        "executions": [
            {
                "identity_id": case["identities"][0]["id"],
                "status_code": 200,
                "observed_outcome": "allow",
                "headers": {"Authorization": "Bearer private-result-fixture-654321"},
            }
        ],
        "findings": [{"severity": "high", "message": "synthetic candidate", "category": "fixture"}],
    }
    return s, args, Results(s["service"]), raw


def submit(pair, raw=None, db=None):
    s, args, service, default = pair
    artifact = json.dumps(default if raw is None else raw)
    return service.submit(
        db or s["db"],
        s["runner"],
        **args,
        artifact=artifact,
        artifact_sha256=hashlib.sha256(artifact.encode()).hexdigest(),
    )


def finish(pair, ack, outcome="completed", db=None, termination_confirmed=True):
    s, args, service, _ = pair
    return service.finish(
        db or s["db"],
        s["runner"],
        **args,
        receipt_sha256=ack["receipt_sha256"],
        outcome=outcome,
        termination_confirmed=termination_confirmed,
    )


def facts(s, terminal=False):
    with Session(s["engine"]) as db:
        assert db.query(ManagedContract).one().consumed
        assert db.query(ManagedApproval).one().issued == 1
        eng = db.get(Engagement, "eng-1")
        assert (eng.targets_spent, eng.duration_allocated) == (1, 30)
        assert db.get(JobExecution, "job-1").capacity_reserved is not terminal
        assert db.query(ManagedResult).count() == db.query(JobResultReceipt).count() == 1
        assert db.query(Evidence).count() == db.query(ScanItem).count() == 1
        assert db.query(ScanItem).one().status == "new"
        assert "private-result-fixture-654321" not in db.query(Evidence).one().body


def test_atomic_evidence_completion_and_observation(results):
    s, args, service, raw = results
    ack = submit(results)
    facts(s)
    before = service.inspect(s["db"], s["runner"], **args)
    assert before["result"] == ack and before["completion"] is None
    done = finish(results, ack)
    assert done["outcome"] == "completed" and done["capacity_reserved"] is False
    assert finish(results, ack) == done
    with pytest.raises(WireRefused, match="different_completion"):
        finish(results, ack, "failed")
    s["wall"][0] += timedelta(minutes=2)
    assert service.inspect(s["db"], s["runner"], **args)["completion"] == done
    assert submit(results) == ack
    facts(s, terminal=True)


def test_changed_result_never_rewrites_receipt(results):
    s, args, service, raw = results
    ack = submit(results)
    with Session(s["engine"]) as db:
        identity = db.query(Evidence).one().id
        db.query(ManagedApproval).one().revoked = True
        db.commit()
    s["wall"][0] += timedelta(minutes=2)
    assert submit(results) == ack
    raw["findings"][0]["message"] = "changed"
    with pytest.raises(WireRefused, match="different_managed_result"):
        submit(results)
    with Session(s["engine"]) as db:
        assert db.query(Evidence).one().id == identity
    facts(s)


@pytest.mark.parametrize(
    "change",
    ["case_hash", "test_case_id", "artifact_hash", "duplicate", "oversize", "shape", "nonfinite"],
)
def test_invalid_artifact_has_no_writes(results, change):
    s, args, service, raw = results
    if change in {"case_hash", "test_case_id"}:
        raw[change] = "wrong"
    artifact = json.dumps(raw)
    artifact = {
        "duplicate": '{"case_hash":"a","case_hash":"b"}',
        "oversize": "x" * 512001,
        "shape": "[]",
        "nonfinite": '{"value":NaN}',
    }.get(change, artifact)
    sha = hashlib.sha256(artifact.encode()).hexdigest() if change != "artifact_hash" else "0" * 64
    with pytest.raises(WireRefused):
        service.submit(s["db"], s["runner"], **args, artifact=artifact, artifact_sha256=sha)
    with Session(s["engine"]) as db:
        assert (
            db.query(ManagedResult).count()
            == db.query(JobResultReceipt).count()
            == db.query(Evidence).count()
            == 0
        )
        assert db.get(JobExecution, "job-1").capacity_reserved


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_id", "other"),
        ("attempt_id", "other"),
        ("fence", True),
        ("contract_sha256", "0" * 64),
    ],
)
def test_foreign_binding_cannot_observe(results, field, value):
    s, args, service, raw = results
    with pytest.raises(WireRefused):
        service.inspect(s["db"], s["runner"], **{**args, field: value})


@pytest.mark.parametrize("denial", ["expired", "revoked", "stopped", "duration"])
def test_success_denial_retains_evidence_and_capacity(results, denial):
    s, args, service, raw = results
    ack = submit(results)
    if denial == "expired":
        s["wall"][0] += timedelta(seconds=11)
    else:
        with Session(s["engine"]) as db:
            if denial == "revoked":
                db.query(ManagedApproval).one().revoked = True
            elif denial == "duration":
                db.get(JobExecution, "job-1").duration_seconds = 1
            else:
                db.get(JobExecution, "job-1").state = "cancel_requested"
            db.commit()
        if denial == "duration":
            s["wall"][0] += timedelta(seconds=2)
    with pytest.raises(WireRefused):
        finish(results, ack)
    facts(s)
    assert finish(results, ack, "failed")["outcome"] == "failed"
    facts(s, terminal=True)


def test_preflight_failure_never_success(results):
    s, args, service, raw = results
    raw["preflight"] = [
        {
            "identity_id": raw["executions"][0]["identity_id"],
            "status": "failed",
            "reason": "credential_rejected",
            "status_code": 401,
        }
    ]
    ack = submit(results)
    with pytest.raises(WireRefused, match="preflight_failure_not_success"):
        finish(results, ack)
    assert finish(results, ack, "failed")["outcome"] == "failed"
    with Session(s["engine"]) as db:
        assert db.query(Evidence).count() == 2


def test_missing_receipt_or_termination_cannot_release(results):
    s, args, service, raw = results
    with pytest.raises(WireRefused, match="owned_result_receipt_required"):
        finish(results, {"receipt_sha256": "0" * 64})
    ack = submit(results)
    for value in (False, 1, None):
        with pytest.raises(WireRefused, match="known_termination_required"):
            finish(results, ack, termination_confirmed=value)
    facts(s)


@pytest.mark.parametrize("phase", ["evidence_write", "completion_delay"])
def test_storage_failure_or_delay_rolls_back_atomically(results, phase):
    s, args, service, raw = results
    ack = submit(results) if phase == "completion_delay" else None

    def fault(conn, cursor, statement, parameters, context, executemany):
        if phase == "evidence_write" and statement.startswith("INSERT INTO managed_results"):
            raise RuntimeError("synthetic receipt failure")
        if phase == "completion_delay" and statement.startswith(
            "UPDATE managed_results SET outcome"
        ):
            s["ticks"][0] = 11

    event.listen(s["engine"], "after_cursor_execute", fault)
    try:
        with pytest.raises(WireRefused if ack else RuntimeError):
            finish(results, ack) if ack else submit(results)
    finally:
        event.remove(s["engine"], "after_cursor_execute", fault)
    with Session(s["engine"]) as db:
        assert db.get(JobExecution, "job-1").capacity_reserved
        assert db.get(ScanJob, "job-1").status == "running"
        if ack:
            assert db.query(ManagedResult).one().outcome is None
        else:
            assert (
                db.query(Evidence).count()
                == db.query(ScanItem).count()
                == db.query(JobResultReceipt).count()
                == 0
            )


def test_concurrent_result_winner(results):
    s, args, service, raw = results

    def attempt(index):
        candidate = copy.deepcopy(raw)
        candidate["findings"][0]["message"] += str(index)
        with Session(s["engine"]) as db:
            try:
                return submit(results, candidate, db)["receipt_sha256"]
            except WireRefused as exc:
                return str(exc)

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(attempt, range(2)))
    assert replies.count("different_managed_result") == 1
    facts(s)


def test_concurrent_completion_one_immutable_outcome(results):
    s, args, service, raw = results
    ack = submit(results)

    def attempt(outcome):
        with Session(s["engine"]) as db:
            try:
                return finish(results, ack, outcome, db)["outcome"]
            except WireRefused as exc:
                return str(exc)

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(attempt, ["completed", "failed"]))
    assert "different_completion" in replies
    facts(s, terminal=True)
