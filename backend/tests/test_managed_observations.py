"""No-capability observation authenticates the original enrolled principal only."""

import copy
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import execution_control as control
from managed_observations import Observations
from managed_results import Results
from managed_stops import Stops
from managed_wire import WireRefused, digest
from models import (
    ApiKey,
    Engagement,
    JobExecution,
    ManagedApproval,
    ManagedContract,
    ManagedEnrollment,
    ScanJob,
)
from tests.test_managed_issuance import KEY, ORIGIN, RUNNER, claim, register, request
from tests.test_managed_issuance import specimen as specimen


@pytest.fixture
def observation(specimen, monkeypatch):
    s = specimen
    monkeypatch.setattr(control, "now", lambda: s["wall"][0].replace(tzinfo=None))
    register(s)
    service = Observations(Results(s["service"]))
    args = dict(
        job_id="job-1",
        body=control.ClaimControl(runner_id=RUNNER, origin=ORIGIN),
        plan_sha256=digest(s["plan"]),
        case_sha256=s["plan"]["case_hash"],
        association_sha256=digest(
            {
                "origin": ORIGIN,
                "runner_id": RUNNER,
                "principal_sha256": hashlib.sha256(("Bearer " + KEY).encode()).hexdigest(),
            }
        ),
    )
    return s, service, args


def inspect(pair, *, db=None, req=None, args=None):
    s, service, original = pair
    return service.inspect(db or s["db"], req or s["runner"], **(args or original))


def control_args(s, issued):
    with Session(s["engine"]) as db:
        c = db.query(ManagedContract).one()
        return dict(
            job_id="job-1",
            body=control.ControlRequest(
                runner_id=RUNNER, origin=ORIGIN, token=issued["execution_control"]["token"]
            ),
            contract_id=c.id,
            attempt_id=c.attempt_id,
            fence=c.fence,
            contract_sha256=digest(c.envelope),
        )


def test_absence_is_only_a_snapshot_and_does_not_reserve_or_block_a_later_claim(observation):
    s, _, _ = observation
    reply = inspect(observation)
    assert reply["claim"] is None and reply["execution_state"] is None
    assert reply["capacity_reserved"] is False
    with Session(s["engine"]) as db:
        assert db.query(JobExecution).count() == db.query(ManagedContract).count() == 0
        assert db.query(ManagedApproval).one().issued == 0
        assert (
            db.get(Engagement, "eng-1").targets_spent,
            db.get(Engagement, "eng-1").duration_allocated,
        ) == (0, 0)
    claim(s)
    assert inspect(observation)["claim"] is not None


def test_claim_observation_never_returns_token_or_renews_permission(observation):
    s, _, _ = observation
    issued = claim(s)
    with Session(s["engine"]) as db:
        expiry = db.get(JobExecution, "job-1").expires_at
    s["wall"][0] += timedelta(minutes=2)
    with Session(s["engine"]) as db:
        db.query(ManagedApproval).one().revoked = True
        db.commit()
    reply = inspect(observation)
    assert reply["claim"]["consumed"] is False and reply["capacity_reserved"] is True
    raw = json.dumps(reply)
    assert KEY not in raw and issued["execution_control"]["token"] not in raw
    assert all(
        value not in raw for value in ('"token"', '"lease_seconds"', '"signature"', '"envelope"')
    )
    with Session(s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == expiry
        assert db.get(ScanJob, "job-1").status == "running"
        assert db.query(ManagedApproval).one().issued == 1
        assert (
            db.get(Engagement, "eng-1").targets_spent,
            db.get(Engagement, "eng-1").duration_allocated,
        ) == (1, 30)


@pytest.mark.parametrize("kind", ["result", "stop"])
def test_owned_terminal_receipts_can_be_observed_without_original_capability(observation, kind):
    import assessments

    s, observer, _ = observation
    issued = claim(s)
    args = control_args(s, issued)
    s["service"].consume(s["db"], s["runner"], **args)
    if kind == "result":
        with Session(s["engine"]) as db:
            case = db.get(ScanJob, "job-1").case_snapshot
        artifact = json.dumps(
            {
                "test_case_id": case["id"],
                "case_hash": assessments.case_hash(case),
                "executions": [],
                "findings": [],
            }
        )
        ack = observer.results.submit(
            s["db"],
            s["runner"],
            **args,
            artifact=artifact,
            artifact_sha256=hashlib.sha256(artifact.encode()).hexdigest(),
        )
        terminal = observer.results.finish(
            s["db"],
            s["runner"],
            **args,
            receipt_sha256=ack["receipt_sha256"],
            outcome="completed",
            termination_confirmed=True,
        )
    else:
        terminal = Stops(observer.results).report(
            s["db"],
            s["runner"],
            **args,
            outcome="cancelled",
            cause="local_emergency_stop",
            termination_confirmed=True,
        )
    s["wall"][0] += timedelta(minutes=2)
    reply = inspect(observation)
    assert reply["claim"]["consumed"] is True and reply["capacity_reserved"] is False
    assert reply["completion" if kind == "result" else "stop"] == terminal
    assert issued["execution_control"]["token"] not in json.dumps(reply)


@pytest.mark.parametrize(
    "field", ["plan_sha256", "case_sha256", "association_sha256", "runner_id", "origin"]
)
def test_changed_fingerprint_or_identity_cannot_observe(observation, field):
    s, _, args = observation
    claim(s)
    changed = copy.deepcopy(args)
    if field in {"runner_id", "origin"}:
        changed["body"] = control.ClaimControl(
            runner_id=str(uuid.UUID(int=99)) if field == "runner_id" else RUNNER,
            origin="https://foreign.example.test" if field == "origin" else ORIGIN,
        )
    else:
        changed[field] = "0" * 64
    with pytest.raises(WireRefused):
        inspect(observation, args=changed)


@pytest.mark.parametrize(
    "change", ["other_key", "jwt", "enrollment_revoked", "key_deleted", "key_scope"]
)
def test_uuid_and_owner_alone_are_not_observation_authority(observation, change):
    s, _, _ = observation
    claim(s)
    req = None
    if change == "other_key":
        other = "vmap_other_public_observation_fixture"
        with Session(s["engine"]) as db:
            db.add(
                ApiKey(
                    id="other-key",
                    github_id="owner-1",
                    key_hash=hashlib.sha256(other.encode()).hexdigest(),
                    scope="full",
                )
            )
            db.commit()
        req = request(other)
    elif change == "jwt":
        req = s["owner"]
    else:
        with Session(s["engine"]) as db:
            if change == "enrollment_revoked":
                db.query(ManagedEnrollment).one().revoked = True
            elif change == "key_deleted":
                db.delete(db.get(ApiKey, "key-1"))
            else:
                db.get(ApiKey, "key-1").scope = "unsupported"
            db.commit()
    with pytest.raises((WireRefused, HTTPException)):
        inspect(observation, req=req)


@pytest.mark.parametrize("broken", ["missing_execution", "missing_contract", "snapshot", "payload"])
def test_inconsistent_retained_claim_is_not_observed_as_absent(observation, broken):
    from sqlalchemy import delete

    s, _, _ = observation
    claim(s)
    with Session(s["engine"]) as db:
        if broken == "missing_execution":
            db.execute(delete(JobExecution))
        elif broken == "missing_contract":
            db.execute(delete(ManagedContract))
        elif broken == "snapshot":
            db.get(ScanJob, "job-1").case_snapshot = {"id": "changed"}
        else:
            db.query(ManagedContract).one().fence = 2
        db.commit()
    with pytest.raises(WireRefused, match="inconsistent_observed_claim"):
        inspect(observation)


def test_concurrent_observation_and_claim_do_not_change_reservation_semantics(observation):
    s, _, _ = observation

    def read():
        with Session(s["engine"]) as db:
            return inspect(observation, db=db)

    def write():
        with Session(s["engine"]) as db:
            return claim(s, db=db)

    with ThreadPoolExecutor(2) as pool:
        observed, claimed = pool.submit(read), pool.submit(write)
        reply, _issued = observed.result(), claimed.result()
    if reply["claim"] is not None:
        assert reply["claim"]["contract_id"] == inspect(observation)["claim"]["contract_id"]
    with Session(s["engine"]) as db:
        assert db.query(JobExecution).count() == db.query(ManagedContract).count() == 1
        assert db.query(ManagedApproval).one().issued == 1
        assert db.get(JobExecution, "job-1").capacity_reserved
