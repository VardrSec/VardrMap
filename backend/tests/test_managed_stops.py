"""Owned stop receipts: no expiration/PID inference, replay, or counter refund."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from managed_results import Results
from managed_stops import CANCEL_CAUSES, CAUSES, Stops
from managed_wire import WireRefused
from models import (
    Engagement,
    Evidence,
    JobExecution,
    JobResultReceipt,
    ManagedApproval,
    ManagedContract,
    ManagedResult,
    ManagedStop,
    ScanItem,
    ScanJob,
)
from tests.test_managed_consumption import consume
from tests.test_managed_consumption import consumption as consumption
from tests.test_managed_issuance import specimen as specimen


@pytest.fixture
def stops(consumption):
    s, args = consumption
    consume(s, args)
    return s, args, Stops(Results(s["service"]))


def report(
    pair,
    *,
    cause="local_emergency_stop",
    outcome=None,
    confirmed=True,
    db=None,
    args=None,
):
    s, original, service = pair
    return service.report(
        db or s["db"],
        s["runner"],
        **(args or original),
        cause=cause,
        outcome=outcome or ("cancelled" if cause in CANCEL_CAUSES else "failed"),
        termination_confirmed=confirmed,
    )


def facts(s, *, terminal=False):
    with Session(s["engine"]) as db:
        assert db.query(ManagedContract).one().consumed
        assert db.query(ManagedApproval).one().issued == 1
        eng = db.get(Engagement, "eng-1")
        assert (eng.targets_spent, eng.duration_allocated) == (1, 30)
        assert db.get(JobExecution, "job-1").capacity_reserved is not terminal
        assert db.query(ManagedStop).count() == int(terminal)


@pytest.mark.parametrize("cause", sorted(CAUSES))
def test_explicit_known_stop_receipt_is_immutable_and_spent(stops, cause):
    s, args, service = stops
    s["wall"][0] += timedelta(minutes=2)
    before = service.inspect(s["db"], s["runner"], **args)
    assert before["stop"] is None and before["capacity_reserved"] is True
    facts(s)
    ack = report(stops, cause=cause)
    assert ack["outcome"] == ("cancelled" if cause in CANCEL_CAUSES else "failed")
    assert report(stops, cause=cause) == ack
    assert service.inspect(s["db"], s["runner"], **args)["stop"] == ack
    facts(s, terminal=True)
    other = "tool_timeout" if cause != "tool_timeout" else "control_lease_expired"
    with pytest.raises(WireRefused, match="different_stop_receipt"):
        report(stops, cause=other)
    facts(s, terminal=True)


@pytest.mark.parametrize(
    "confirmed,cause,outcome",
    [
        (False, "tool_timeout", "failed"),
        (1, "tool_timeout", "failed"),
        (True, "execution_state_uncertain", "failed"),
        (True, "arbitrary raw error", "failed"),
        (True, "tool_timeout", "cancelled"),
        (True, "local_emergency_stop", "completed"),
    ],
)
def test_uncertain_or_wrong_stop_reports_never_release(
    stops, confirmed, cause, outcome
):
    s, _, _ = stops
    with pytest.raises(WireRefused, match="known_stop_report_required"):
        report(stops, cause=cause, outcome=outcome, confirmed=confirmed)
    facts(s)


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_id", "foreign"),
        ("attempt_id", "foreign"),
        ("fence", True),
        ("contract_sha256", "0" * 64),
    ],
)
def test_foreign_tuple_never_releases(stops, field, value):
    s, args, service = stops
    with pytest.raises(WireRefused):
        report(stops, args={**args, field: value})
    facts(s)


def test_missing_consumption_or_foreign_terminal_state_cannot_be_adopted(stops):
    s, args, service = stops
    with Session(s["engine"]) as db:
        db.query(ManagedContract).one().consumed = False
        db.commit()
    with pytest.raises(WireRefused, match="owned_consumed_contract_required"):
        report(stops)
    with Session(s["engine"]) as db:
        db.query(ManagedContract).one().consumed = True
        db.get(JobExecution, "job-1").state = "failed"
        db.get(JobExecution, "job-1").capacity_reserved = False
        db.commit()
    with pytest.raises(WireRefused, match="owned_reservation_required"):
        report(stops)
    with Session(s["engine"]) as db:
        assert db.query(ManagedStop).count() == 0


@pytest.mark.parametrize("first", ["result", "stop"])
@pytest.mark.parametrize("permission", ["active", "expired", "approval_revoked"])
def test_result_and_stop_receipts_are_mutually_exclusive(stops, first, permission):
    import hashlib
    import json

    import assessments

    s, args, service = stops
    with Session(s["engine"]) as db:
        case = db.get(ScanJob, "job-1").case_snapshot
        if permission == "approval_revoked":
            db.query(ManagedApproval).one().revoked = True
            db.commit()
    if permission == "expired":
        s["wall"][0] += timedelta(minutes=2)
    artifact = json.dumps(
        {
            "case_hash": assessments.case_hash(case),
            "test_case_id": case["id"],
            "executions": [
                {
                    "identity_id": case["identities"][0]["id"],
                    "status_code": 200,
                    "observed_outcome": "allow",
                }
            ],
            "findings": [{"severity": "high", "message": "synthetic candidate"}],
        }
    )

    def upload():
        return service.results.submit(
            s["db"],
            s["runner"],
            **args,
            artifact=artifact,
            artifact_sha256=hashlib.sha256(artifact.encode()).hexdigest(),
        )

    if first == "result":
        result_ack = upload()
        with pytest.raises(WireRefused, match="result_protocol_already_started"):
            report(stops)
        assert upload() == result_ack
    else:
        stop_ack = report(stops)
        with pytest.raises(WireRefused, match="stop_protocol_already_started"):
            upload()
        assert report(stops) == stop_ack
    facts(s, terminal=first == "stop")
    with Session(s["engine"]) as db:
        expected = int(first == "result")
        assert (
            db.query(ManagedResult).count()
            == db.query(JobResultReceipt).count()
            == db.query(Evidence).count()
            == db.query(ScanItem).count()
            == expected
        )


def test_receipt_write_failure_rolls_back_release(stops):
    s, _, _ = stops

    def fault(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO managed_stops"):
            raise RuntimeError("synthetic receipt write failure")

    event.listen(s["engine"], "after_cursor_execute", fault)
    try:
        with pytest.raises(RuntimeError):
            report(stops)
    finally:
        event.remove(s["engine"], "after_cursor_execute", fault)
    facts(s)
    with Session(s["engine"]) as db:
        assert db.get(ScanJob, "job-1").status == "running"


def test_concurrent_reports_have_one_immutable_stop_outcome(stops):
    s, _, _ = stops

    def attempt(cause):
        with Session(s["engine"]) as db:
            try:
                return report(stops, cause=cause, db=db)["cause"]
            except WireRefused as exc:
                return str(exc)

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(attempt, ["local_emergency_stop", "tool_timeout"]))
    assert replies.count("different_stop_receipt") == 1
    facts(s, terminal=True)


def test_stop_receipt_survives_job_deletion(stops):
    from sqlalchemy import delete

    s, _, _ = stops
    ack = report(stops)
    with Session(s["engine"]) as db:
        db.execute(delete(ScanJob).where(ScanJob.id == "job-1"))
        db.commit()
        assert db.query(ManagedStop).one().receipt_sha256 == ack["receipt_sha256"]
        assert db.query(ManagedContract).one().consumed
        assert db.query(ManagedApproval).one().issued == 1


def test_inconsistent_retained_execution_is_not_a_release_receipt(stops):
    s, args, service = stops
    report(stops)
    with Session(s["engine"]) as db:
        db.get(JobExecution, "job-1").capacity_reserved = True
        db.commit()
    with pytest.raises(WireRefused, match="retained_stop_inconsistent"):
        service.inspect(s["db"], s["runner"], **args)
