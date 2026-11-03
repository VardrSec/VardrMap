"""Real pre-claim/local handoff, no production Map route/schema or remote finalization."""

import hashlib
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import execution_control as map_control
import pytest
from db import get_db
from fastapi import Depends, Request
from models import Engagement, JobExecution, ManagedApproval, ScanJob
from sqlalchemy.orm import Session
from tests.test_managed_http import harness as harness
from tests.test_managed_issuance import KEY, RUNNER
from tests.test_managed_issuance import specimen as specimen
from tests.test_managed_native import native as native
from tests.test_managed_tls import map_origin as map_origin
from tests.test_managed_tls import tls_harness as tls_harness
from tests.test_managed_tls import tls_socket as tls_socket

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("NM2_PRECLAIM_ENTRY") != "1",
    reason="explicit preclaim native integration only",
)


@pytest.fixture
def entry(native, tmp_path):
    n = native
    from vardrrunner import config
    from vardrrunner.authorization.claim import ManagedEntry
    from vardrrunner.journal import Journal

    @n.t.h.app.post("/entry/claim")
    def claim(body: dict, request: Request, db=Depends(get_db)):
        result = n.t.h.service.claim(
            db, request, job_id="job-1", body=map_control.ClaimControl(**body)
        )
        db.expire_all()
        result["config"] = {"test_case": db.get(ScanJob, "job-1").case_snapshot}
        return result

    def make(transport):
        return ManagedEntry(
            Journal(config.journal_file()),
            map_origin=n.t.h.origin,
            runner_id=RUNNER,
            engagement_id="eng-1",
            job_id="job-1",
            principal_sha256=hashlib.sha256(("Bearer " + KEY).encode()).hexdigest(),
            case=n.case,
            execution=n.plan["execution"],
            allocated_seconds=30,
            anchors=n.anchors,
            claim=lambda body: transport.client.post("/entry/claim", json=body),
            current=lambda body: transport.client.post("/fixture/current", json=body),
            consume=lambda body: transport.client.post("/fixture/consume", json=body),
        )

    directory = tmp_path / "entry-artifact"
    directory.mkdir()
    return SimpleNamespace(n=n, make=make, directory=directory)


def facts(e, case, handle=None):
    from vardrrunner import config
    from vardrrunner.journal import Journal
    from vardrrunner.recovery import reconcile

    with Session(e.n.t.h.s["engine"]) as db:
        execution = db.get(JobExecution, "job-1")
        assert execution.capacity_reserved
        assert db.get(Engagement, "eng-1").targets_spent == 1
        assert db.get(Engagement, "eng-1").duration_allocated == 30
        assert db.query(ManagedApproval).one().issued == 1
    journal = Journal(config.journal_file())
    client = Mock()
    assert reconcile(journal, client, e.n.t.h.origin).deferred == 1
    assert not client.mock_calls
    with journal._connection() as con:
        intent = dict(con.execute("SELECT * FROM managed_claim_intents").fetchone())
        run = dict(con.execute("SELECT * FROM runs").fetchone())
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='authorization_contracts'"
        ).fetchone()
        consumed = (
            con.execute("SELECT count(*) FROM authorization_contracts WHERE consumed=1").fetchone()[
                0
            ]
            if exists
            else 0
        )
        dump = "\n".join(con.iterdump())
    assert KEY not in dump and "vardr.authorization-envelope" not in dump
    assert e.n.case["request"]["url"] not in dump
    assert all(not path.exists() and not folder.exists() for path, folder in e.n.private_files)
    directory = Path(os.environ["TEMP"]) / "entry-cases"
    directory.mkdir(exist_ok=True)
    result = {
        "schema": "vardr.preclaim-fixture/1",
        "case": case,
        "intent_state": intent["state"],
        "run_phase": run["phase"],
        "claim_requests": e.n.t.wire.seen.get("/entry/claim", 0),
        "map_reservation_retained": True,
        "remote_outcome_not_fabricated": True,
        "local_consumed": consumed,
        "target_contacts": len(e.n.seen),
        "recovery_transport_calls": 0,
        "sensitive_journal_values": False,
        "private_files_removed": True,
    }
    if handle is not None:
        result.update(
            anchor_utc=handle.gate._anchor.isoformat(),
            anchor_mono=handle.gate._entered,
            persisted_anchor_utc=intent["utc_anchor"],
            persisted_anchor_mono=intent["mono_anchor"],
        )
        assert result["anchor_utc"] == result["persisted_anchor_utc"]
        assert result["anchor_mono"] == result["persisted_anchor_mono"]
    (directory / (case + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    return result


def test_actual_preclaim_entry_to_native_local_artifact(entry):
    e = entry
    with e.n.t.serve():
        e.n.authorize()
        transport = e.n.t.transport()
        facade = e.make(transport)
        handle = facade.acquire(e.directory)
        e.n.attempts.append(handle.gate)
        output = handle.execute(e.directory)
        assert output.is_file()
        record = facade.journal.get(handle.run_id)
        assert record.artifact_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
        assert record.pid is None
    result = facts(e, "entry_artifact", handle)
    assert result["local_consumed"] == 1 and result["run_phase"] == "artifact_ready"
    assert result["claim_requests"] == 1 and result["target_contacts"] > 0


def test_actual_lost_claim_reply_never_retries_after_restart(entry):
    from vardrrunner.authorization.codec import AuthorizationError
    from vardrrunner.authorization.claim import ClaimError

    e = entry
    with e.n.t.serve():
        e.n.authorize()
        transport = e.n.t.transport()
        e.n.t.wire.mode = "drop_claim"
        with pytest.raises(ClaimError, match="claim_outcome_unknown"):
            e.make(transport).acquire(e.directory)
        with pytest.raises(AuthorizationError, match="existing_invocation"):
            e.make(transport).acquire(e.directory)
    result = facts(e, "lost_claim")
    assert result["intent_state"] == "claim_unknown" and result["claim_requests"] == 1
    assert result["local_consumed"] == 0 and result["target_contacts"] == 0


def test_actual_binding_write_failure_retains_server_slot(entry, monkeypatch):
    from vardrrunner.authorization.claim import ClaimError, ClaimStore
    from vardrrunner.journal import JournalError

    e = entry

    def fail(*args):
        raise JournalError("synthetic binding failure")

    monkeypatch.setattr(ClaimStore, "bind", fail)
    with e.n.t.serve():
        e.n.authorize()
        with pytest.raises(ClaimError, match="handoff_held"):
            e.make(e.n.t.transport()).acquire(e.directory)
    result = facts(e, "binding_failure")
    assert result["intent_state"] == "reply_or_binding_unknown"
    assert result["local_consumed"] == 0 and result["target_contacts"] == 0


def test_actual_local_journal_stop_is_used_by_native_entry(entry):
    from vardrrunner.execution_control import ExecutionStopped
    from vardrrunner.windows_job import process_running

    e = entry
    e.n.behavior["hold"] = True
    errors = []
    with e.n.t.serve():
        e.n.authorize()
        facade = e.make(e.n.t.transport())
        handle = facade.acquire(e.directory)
        e.n.attempts.append(handle.gate)

        def stop():
            try:
                assert e.n.started.wait(12)
                facade.journal.request_stop(handle.run_id)
            except Exception as error:
                errors.append(type(error).__name__)

        thread = threading.Thread(target=stop, daemon=True)
        thread.start()
        with pytest.raises(ExecutionStopped, match="local_emergency_stop") as stopped:
            handle.execute(e.directory)
        thread.join(3)
        assert not thread.is_alive() and not errors and stopped.value.confirmed
        record = facade.journal.get(handle.run_id)
        assert record.pid is not None and not process_running(record.pid)
    result = facts(e, "local_stop", handle)
    assert result["intent_state"] == "held_after_claim" and result["local_consumed"] == 1


def test_actual_native_artifact_managed_finalization_and_receipt(entry):
    """Deferred real Windows gate; no cloud fixture may certify this test."""
    from models import ManagedContract, ManagedResult

    e = entry
    with e.n.t.serve():
        e.n.authorize()
        transport = e.n.t.transport()
        handle = e.make(transport).acquire(e.directory)
        e.n.attempts.append(handle.gate)
        handle.execute(e.directory)
        handle.finalize(
            lambda body: transport.client.post("/fixture/result", json=body),
            lambda body: transport.client.post("/fixture/finish", json=body),
        )
    with Session(e.n.t.h.s["engine"]) as db:
        assert db.query(ManagedResult).one().outcome == "completed"
        assert db.query(ManagedContract).one().consumed
        assert db.get(JobExecution, "job-1").state == "completed"
        assert not db.get(JobExecution, "job-1").capacity_reserved
        assert db.query(ManagedApproval).one().issued == 1
        assert db.get(Engagement, "eng-1").targets_spent == 1
        assert db.get(Engagement, "eng-1").duration_allocated == 30
