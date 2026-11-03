"""Disposable one-shot acknowledgement; no routes, targets, or finalization."""

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import execution_control as control
import pytest
from managed_wire import WireRefused, digest
from models import Engagement, JobExecution, ManagedApproval, ManagedContract
from sqlalchemy import event
from sqlalchemy.orm import Session

from tests.test_managed_issuance import NOW, ORIGIN, RUNNER, claim, register
from tests.test_managed_issuance import specimen as specimen


@pytest.fixture
def consumption(specimen, monkeypatch):
    s = specimen
    monkeypatch.setattr(control, "now", lambda: s["wall"][0].replace(tzinfo=None))
    register(s)
    issued = claim(s)
    row = s["db"].query(ManagedContract).one()
    args = dict(
        job_id="job-1",
        body=control.ControlRequest(
            runner_id=RUNNER, origin=ORIGIN, token=issued["execution_control"]["token"]
        ),
        contract_id=row.id,
        attempt_id=row.attempt_id,
        fence=row.fence,
        contract_sha256=digest(row.envelope),
    )
    s["db"].rollback()
    return s, args


def consume(s, args, db=None):
    return s["service"].consume(db or s["db"], s["runner"], **args)


def retained(s, consumed):
    with Session(s["engine"]) as db:
        assert db.query(ManagedContract).one().consumed is consumed
        assert db.get(JobExecution, "job-1").capacity_reserved
        assert db.get(JobExecution, "job-1").state == "active"
        assert db.query(ManagedApproval).one().issued == 1
        eng = db.get(Engagement, "eng-1")
        assert (eng.targets_spent, eng.duration_allocated) == (1, 30)


def test_one_acknowledgement_never_renews_or_releases(consumption):
    s, args = consumption
    with Session(s["engine"]) as db:
        expiry = db.get(JobExecution, "job-1").expires_at
    ack = consume(s, args)
    assert ack == {
        "schema": "vardr.managed-consumption/1",
        "consumed": True,
        "job_id": "job-1",
        "origin": ORIGIN,
        "runner_id": RUNNER,
        "authority_revision": s["review"]["context"]["authority_revision"],
        "authority_sha256": s["review"]["context"]["authority_sha256"],
        **{k: args[k] for k in ("contract_id", "attempt_id", "fence", "contract_sha256")},
    }
    with pytest.raises(WireRefused, match="already_consumed"):
        consume(s, args)
    retained(s, True)
    with Session(s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == expiry


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_id", "other"),
        ("attempt_id", "other"),
        ("fence", 2),
        ("fence", True),
        ("contract_sha256", "0" * 64),
        ("contract_sha256", None),
    ],
)
def test_changed_contract_cannot_consume(consumption, field, value):
    s, args = consumption
    with pytest.raises(WireRefused):
        consume(s, {**args, field: value})
    retained(s, False)


@pytest.mark.parametrize("change", ["token", "revoked", "expired", "stopped"])
def test_permission_denials_do_not_acknowledge(consumption, change):
    from fastapi import HTTPException

    s, args = consumption
    args = copy.deepcopy(args)
    if change == "token":
        args["body"].token = "z" * 40
    elif change == "expired":
        s["wall"][0] = NOW + timedelta(seconds=11)
    else:
        with Session(s["engine"]) as db:
            if change == "revoked":
                db.query(ManagedApproval).one().revoked = True
            else:
                db.get(JobExecution, "job-1").state = "stop_requested"
            db.commit()
    with pytest.raises((WireRefused, HTTPException)):
        consume(s, args)
    with Session(s["engine"]) as db:
        assert not db.query(ManagedContract).one().consumed
        assert db.get(JobExecution, "job-1").capacity_reserved


def test_delayed_consumption_write_rolls_back(consumption):
    s, args = consumption

    def delayed(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE managed_contracts SET consumed"):
            s["ticks"][0] = 11

    event.listen(s["engine"], "after_cursor_execute", delayed)
    try:
        with pytest.raises(WireRefused, match="expired_or_stopped"):
            consume(s, args)
    finally:
        event.remove(s["engine"], "after_cursor_execute", delayed)
    retained(s, False)


def test_independent_connections_have_only_one_ack(consumption):
    s, args = consumption

    def attempt():
        with Session(s["engine"]) as db:
            try:
                consume(s, args, db)
                return "ack"
            except WireRefused as exc:
                return str(exc)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["ack", "contract_already_consumed"]
    retained(s, True)
