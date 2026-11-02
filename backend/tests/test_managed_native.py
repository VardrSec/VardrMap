"""Explicit Windows/Gate integration: real clocks, owned process, synthetic loopback only."""

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import execution_control as map_control
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from db import get_db
from deps import get_current_user
from fastapi import BackgroundTasks, Depends
from managed_wire import b64, canonical, message, stamp
from models import (
    Authorization,
    AuthorizationTestCase,
    Engagement,
    JobExecution,
    ManagedApproval,
    ManagedContract,
    ScopeItem,
)
from sqlalchemy.orm import Session
from tests.test_managed_http import harness as harness
from tests.test_managed_issuance import KEY, RUNNER
from tests.test_managed_issuance import specimen as specimen
from tests.test_managed_tls import map_origin as map_origin
from tests.test_managed_tls import tls_harness as tls_harness
from tests.test_managed_tls import tls_socket as tls_socket

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("NM2_NATIVE_GATE") != "1",
    reason="explicit Windows real Gate/loopback fixture only",
)
GATE_SHA = "2a89debd92eb30385da0b2949061cdd02cb5399cf5435adecc98e214eb6f55c0"


@pytest.fixture
def native(tls_harness, tmp_path, monkeypatch):
    t, h = tls_harness, tls_harness.h
    from vardrrunner import (
        config,
        credential_grants,
        execution_control,
        handlers,
        launch_guard,
        runner,
    )
    from vardrrunner.authorization.codec import TrustAnchor, verify
    from vardrrunner.authorization.contracts import ValidationContext, approved
    from vardrrunner.authorization.ledger import AuthorizationLedger
    from vardrrunner.authorization.managed import ManagedGate
    from vardrrunner.authorization.plan import compile_gate_plan
    from vardrrunner.journal import Journal

    binary = Path(os.environ["NM2_NATIVE_GATE_BINARY"])
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == GATE_SHA
    receipt = json.loads(Path(os.environ["NM2_NATIVE_GATE_RECEIPT"]).read_text())
    assert receipt["tool_sha256"] == GATE_SHA
    assert set(receipt["phases"]) == {"setup", "preflight", "resource", "verification", "reset"}
    source = Path(os.environ["NM2_GUARDED_FIXTURE_SOURCE"])
    spec = importlib.util.spec_from_file_location("nm2_existing_guarded_fixture", source)
    existing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(existing)

    started, release = threading.Event(), threading.Event()
    seen = []
    behavior = {"delay": 0.0, "hold": False}

    class Target(existing.Target):
        calls, value = 0, 0

        def respond(self, status, body):
            try:
                super().respond(status, body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            seen.append(("GET", self.path))
            super().do_GET()

        def do_POST(self):
            seen.append(("POST", self.path))
            super().do_POST()

        def do_PATCH(self):
            seen.append(("PATCH", self.path))
            if self.actor() == "owner":
                started.set()
                if behavior["hold"]:
                    release.wait(35)
                elif behavior["delay"]:
                    time.sleep(behavior["delay"])
            super().do_PATCH()

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    target.daemon_threads = True
    thread = threading.Thread(target=target.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{target.server_port}"
    profile = tmp_path / "native-profile"
    profile.mkdir()
    tools = tmp_path / "fixture-binary"
    tools.mkdir()
    copied = tools / "vardrgate.exe"
    shutil.copyfile(binary, copied)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("VARDRRUNNER_ALLOW_PRIVATE_TARGETS", "1")
    monkeypatch.setattr(config, "CONFIG_DIR", profile)
    monkeypatch.setattr(config, "CONFIG_FILE", profile / "config.json")
    monkeypatch.setattr(config, "JOURNAL_FILE", profile / "journal.sqlite3")
    monkeypatch.setattr(config, "TOOLS_DIR", profile / "managed-tools")
    monkeypatch.setattr(map_control, "now", lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    monkeypatch.setattr(
        launch_guard, "time", time
    )  # Undo only the ASGI fixture's deterministic clock.
    h.service.clock = lambda: datetime.now(timezone.utc)
    h.service.monotonic = time.monotonic
    now = datetime.now(timezone.utc).replace(microsecond=0)

    def person(name):
        reference = "NM2_NATIVE_" + name.upper()
        monkeypatch.setenv(reference, "synthetic-" + name)
        return {
            "id": name,
            "credential": {"type": "bearer", "value_env": reference},
            "preflight": {
                "url": origin + "/me",
                "expected_status": 200,
                "json_fields": {"id": name},
            },
        }

    case = {
        "id": "native-case",
        "mutating": True,
        "identities": [person("owner"), person("peer")],
        "setup": [{"name": "prepare", "request": {"method": "POST", "url": origin + "/prepare"}}],
        "request": {"method": "PATCH", "url": origin + "/object", "body": {"value": 1}},
        "expected_access": [
            {"identity_id": "owner", "decision": "allow"},
            {"identity_id": "peer", "decision": "deny"},
        ],
        "write_verification": {
            "strategy": "changed",
            "environment": "synchronous_isolated",
            "identity": person("reader"),
            "request": {"method": "GET", "url": origin + "/object"},
            "json_pointer": "/value",
            "changed_to": 1,
            "reset": {"as": "owner", "request": {"method": "POST", "url": origin + "/reset"}},
        },
    }
    execution = {"allow_private_targets": True, "timeout_seconds": 25}
    plan = compile_gate_plan(case, execution, tool_sha256=GATE_SHA)
    with Session(h.s["engine"]) as db:
        authority = db.get(Authorization, "auth-1")
        authority.window_start, authority.window_end = (
            now - timedelta(minutes=1),
            now + timedelta(minutes=3),
        )
        db.get(AuthorizationTestCase, "case-1").spec = case
        db.query(ScopeItem).one().value = origin
        db.get(Engagement, "eng-1").duration_limit = 300
        db.commit()
    grants = [
        {
            "identity_id": name,
            "source": "value_env",
            "name": "NM2_NATIVE_" + name.upper(),
            "revision": 1,
            "expires_at": stamp(now + timedelta(minutes=2)),
        }
        for name in ("owner", "peer", "reader")
    ]
    h.review.update(
        plan=plan,
        expires_at=stamp(now + timedelta(minutes=2)),
        max_duration_seconds=30,
        credential_grants=grants,
    )
    import target_budget

    h.body.update(duration_seconds=30, target_binding=target_budget.binding(case))
    for _, source_name, name in handlers.credential_references(case):
        credential_grants.Store().approve(h.origin, "eng-1", origin, source_name, name, 90)
    anchors = tuple(
        TrustAnchor(
            "managed-fixture",
            key_id,
            Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw(),
            frozenset({purpose}),
            frozenset({"map"}),
        )
        for key_id, seed, purpose in (
            ("operator-1", bytes(range(32)), "approval"),
            ("contract-1", bytes(range(32, 64)), "contract"),
        )
    )

    @h.app.post("/native/cancel")
    def cancel(user=Depends(get_current_user), db=Depends(get_db)):
        from routers.jobs import JobStatusUpdate, update_job

        return update_job("job-1", JobStatusUpdate(status="failed"), BackgroundTasks(), user, db)

    @h.app.post("/native/stop")
    def stop(user=Depends(get_current_user), db=Depends(get_db)):
        from routers.engagements import StopWorkRequest, engage_stop_work

        return engage_stop_work(
            "eng-1", StopWorkRequest(reason="synthetic native fixture"), user, db
        )

    attempts, private_files = [], []
    original_private = runner._write_private_job

    def private_job(value):
        path, folder = original_private(value)
        private_files.append((path, folder))
        return path, folder

    monkeypatch.setattr(runner, "_write_private_job", private_job)

    def authorize():
        operator = t.transport(token=h.owner["Authorization"].split(" ", 1)[1])
        review = operator.client.post("/fixture/review", json=h.review)
        payload = {
            "schema": "vardr.execution-approval/1",
            "issuer": {"id": "managed-fixture", "key_id": "operator-1"},
            "origin": "map",
            "approval_id": "native-owner-approval",
            "approver_id": "owner-1",
            "approved_at": stamp(datetime.now(timezone.utc)),
            "context": review["context"],
        }
        data = canonical(payload)
        approval = {
            "format": "vardr.authorization-envelope/1",
            "purpose": "approval",
            "payload": b64(data),
            "signature": b64(
                Ed25519PrivateKey.from_private_bytes(bytes(range(32))).sign(
                    message("approval", data)
                )
            ),
        }
        operator.client.post(
            "/fixture/register",
            json={
                **{k: h.review[k] for k in ("job_id", "enrollment_id", "authorization_id", "plan")},
                "approval": approval,
            },
        )
        transport = t.transport()
        return operator, transport, approval

    def issue():
        operator, transport, approval = authorize()
        entered = time.monotonic()
        claim = transport.client.post("/fixture/claim", json=h.body)
        contract = verify(claim["managed_authorization"]["contract"], anchors, "contract")
        permission = approved(approval, anchors)["context"]
        context = ValidationContext(
            RUNNER,
            "eng-1",
            "job-1",
            contract["attempt_id"],
            contract["fence"],
            "map",
            datetime.now(timezone.utc),
            permission["authority_revision"],
            GATE_SHA,
            permission["authority_sha256"],
        )
        attempt = ManagedGate(
            claim,
            anchors,
            AuthorizationLedger(
                Journal(config.journal_file()), clock=lambda: datetime.now(timezone.utc)
            ),
            context,
            copy.deepcopy(case),
            copy.deepcopy(execution),
            map_origin=h.origin,
            principal_sha256=hashlib.sha256(("Bearer " + KEY).encode()).hexdigest(),
            claim_started=entered,
            allocated_seconds=30,
            current=lambda body: transport.client.post("/fixture/current", json=body),
        )
        attempts.append(attempt)
        return attempt, operator

    try:
        yield SimpleNamespace(
            t=t,
            issue=issue,
            authorize=authorize,
            anchors=anchors,
            attempts=attempts,
            seen=seen,
            started=started,
            release=release,
            behavior=behavior,
            case=case,
            binary=copied,
            profile=profile,
            plan=plan,
            private_files=private_files,
            runner=runner,
            grants=credential_grants,
            control=execution_control,
        )
    finally:
        release.set()
        for attempt in attempts:
            if attempt.control is not None:
                attempt.control._thread.join(4)
                assert not attempt.control._thread.is_alive()
        target.shutdown()
        target.server_close()
        thread.join(3)
        assert not thread.is_alive()


def assert_retained(native):
    with Session(native.t.h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").capacity_reserved
        assert db.get(Engagement, "eng-1").targets_spent == 1
        assert db.get(Engagement, "eng-1").duration_allocated == 30
        assert db.query(ManagedApproval).one().issued == 1
        assert db.query(ManagedContract).one().consumed is False
    assert native.private_files and all(
        not path.exists() and not folder.exists() for path, folder in native.private_files
    )
    with sqlite3.connect(native.profile / "journal.sqlite3") as con:
        assert con.execute(
            "SELECT consumed,fence,ordinal FROM authorization_contracts"
        ).fetchall() == [(1, 1, 1)]


def proof(native, name, values):
    directory = Path(os.environ["NM2_NATIVE_RESULTS"]).resolve()
    assert directory.is_relative_to(Path(os.environ["TEMP"]).resolve())
    directory.mkdir(exist_ok=True)
    with Session(native.t.h.s["engine"]) as db:
        server_lease = db.get(JobExecution, "job-1").expires_at.isoformat() + "Z"
    record = {
        "schema": "vardr.native-managed-fixture/1",
        "case": name,
        "gate_sha256": GATE_SHA,
        "real_utc_monotonic": True,
        "server_lease_utc_final": server_lease,
        "target_contacts": len(native.seen),
        "private_files_removed": True,
        "map_reservation_retained": True,
        "map_completion": "unsupported; not attempted",
        "local_contract_consumed": 1,
        **values,
    }
    (directory / (name + ".json")).write_text(json.dumps(record, indent=2) + "\n")


def test_real_gate_healthy_renewal_past_initial_lease(native, tmp_path):
    n, pids = native, []
    n.behavior["delay"] = 12
    with n.t.serve():
        gate, _ = n.issue()
        folder = tmp_path / "result"
        folder.mkdir()
        entered = time.monotonic()
        with n.runner.observe_process(pids.append):
            output = gate.execute(folder)
        assert time.monotonic() - entered > 10
        result = json.loads(output.read_text())
        assert (
            result["case_hash"]
            == hashlib.sha256(
                json.dumps(n.case, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        assert not any(
            "synthetic-" + name in output.read_text() for name in ("owner", "peer", "reader")
        )
        assert set(n.seen) >= {
            ("POST", "/prepare"),
            ("GET", "/me"),
            ("PATCH", "/object"),
            ("GET", "/object"),
            ("POST", "/reset"),
        }
        from vardrrunner.windows_job import process_running

        assert len(pids) == 1 and not process_running(pids[0])
    assert_retained(n)  # Local success does not complete or release managed Map state.
    from collections import Counter
    from urllib.parse import urlsplit

    expected = Counter()
    for dispatch in n.plan["dispatches"]:
        expected[(dispatch["request"]["method"], urlsplit(dispatch["request"]["url"]).path)] += (
            dispatch["max_dispatches"]
        )
    assert all(count <= expected[contact] for contact, count in Counter(n.seen).items())
    assert len(n.seen) <= n.plan["max_http_dispatches"]
    proof(
        n,
        "healthy",
        {
            "elapsed_seconds": time.monotonic() - entered,
            "native_pids": pids,
            "artifact_case_hash_bound": True,
            "artifact_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "case_sha256": result["case_hash"],
            "plan_sha256": hashlib.sha256(
                json.dumps(n.plan, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "all_auxiliary_phases": True,
        },
    )


@pytest.mark.parametrize(
    "reason", ["cancel", "stop", "lost_response", "server_loss", "cached", "grant"]
)
def test_actual_gate_stops_and_retains_ambiguous_managed_state(native, tmp_path, reason):
    n, pids, faults, timing = native, [], [], {}
    n.behavior["hold"] = True
    with n.t.serve() as server:
        if reason == "cached":
            n.t.wire.mode = "capture_current"
        gate, operator = n.issue()
        folder = tmp_path / "stopped"
        folder.mkdir()

        def intervene():
            try:
                assert n.started.wait(12)
                timing["trigger_mono"] = time.monotonic()
                if reason in {"cancel", "stop"}:
                    operator.client.post("/native/" + reason, json={})
                    with Session(n.t.h.s["engine"]) as db:
                        assert (
                            db.get(JobExecution, "job-1").state == "cancel_requested"
                            if reason == "cancel"
                            else db.get(Engagement, "eng-1").stop_work_at is not None
                        )
                elif reason == "lost_response":
                    n.t.wire.mode = "drop_current"
                elif reason == "server_loss":
                    server.should_exit = True
                    until = time.monotonic() + 5
                    while (
                        any(item.is_serving() for item in server.servers)
                        and time.monotonic() < until
                    ):
                        time.sleep(0.02)
                    assert not any(item.is_serving() for item in server.servers)
                elif reason == "cached":
                    # Keep only one successful current response, not all of the
                    # prelaunch observations collected by the capture fixture.
                    with gate._refresh_lock:
                        n.t.wire.cached = n.t.wire.cached[-2:]
                        assert [m["type"] for m in n.t.wire.cached] == [
                            "http.response.start",
                            "http.response.body",
                        ]
                        captured = json.loads(n.t.wire.cached[-1]["body"])
                        assert all(captured[key] == value for key, value in gate.binding.items())
                        timing["current_forwarded_at_cache"] = n.t.wire.forwarded[
                            "/fixture/current"
                        ]
                        n.t.wire.mode = "replay_current"
                else:
                    assert n.grants.Store().revoke(
                        n.t.h.origin,
                        "eng-1",
                        n.case["request"]["url"].rsplit("/", 1)[0],
                        "env",
                        "NM2_NATIVE_OWNER",
                    )
                timing["intervention_verified_mono"] = time.monotonic()
            except Exception as error:
                faults.append(type(error).__name__)

        changer = threading.Thread(target=intervene, daemon=True)
        changer.start()
        with (
            n.runner.observe_process(pids.append),
            pytest.raises(n.control.ExecutionStopped) as stopped,
        ):
            gate.execute(folder)
        timing["terminated_mono"] = time.monotonic()
        changer.join(4)
        assert not changer.is_alive() and not faults
        assert stopped.value.confirmed
        expected_reason = "local_emergency_stop" if reason == "grant" else "control_lease_expired"
        assert str(stopped.value) == expected_reason
        assert (
            timing["trigger_mono"]
            <= timing["intervention_verified_mono"]
            <= timing["terminated_mono"]
        )
        last_verified = gate.lease_deadline()
        assert timing["terminated_mono"] <= last_verified + gate.control.grace + 2.5
        assert timing["terminated_mono"] < gate.hard_end - 3
        if reason == "cached":
            assert n.t.wire.forwarded["/fixture/current"] == timing["current_forwarded_at_cache"]
        from vardrrunner.windows_job import process_running

        assert len(pids) == 1 and not process_running(pids[0])
        contacts = len(n.seen)
        time.sleep(0.2)
        assert len(n.seen) == contacts
    assert_retained(n)
    proof(
        n,
        reason,
        {
            **timing,
            "last_verified_lease_mono": last_verified,
            "immutable_hard_end_mono": gate.hard_end,
            "cleanup_bound_seconds": gate.control.grace + 2.5,
            "stop_cause": str(stopped.value),
            "termination_confirmed": True,
            "native_pids": pids,
        },
    )


@pytest.mark.parametrize(
    "reason", ["grant", "stop", "binary", "auxiliary", "expiry", "permit_stop", "permit_expiry"]
)
def test_real_preparation_change_prevents_gate_contact(native, tmp_path, monkeypatch, reason):
    n, pids = native, []
    with n.t.serve():
        if reason in {"expiry", "permit_expiry"}:
            from vardrrunner import handlers

            for _, source, name in handlers.credential_references(n.case):
                n.grants.Store().approve(
                    n.t.h.origin,
                    "eng-1",
                    n.case["request"]["url"].rsplit("/", 1)[0],
                    source,
                    name,
                    8,
                )
            expiry = min(
                n.grants.timestamp(row["expires_at"]).timestamp()
                for row in n.grants.Store().entries()
            )
        gate, operator = n.issue()
        original = n.runner.config.tool_environment
        changed = []

        def preparation():
            if reason.startswith("permit_"):
                return original()
            if not changed:
                changed.append(True)
                if reason == "stop":
                    operator.client.post("/native/stop", json={})
                elif reason == "grant":
                    n.grants.Store().revoke(
                        n.t.h.origin,
                        "eng-1",
                        n.case["request"]["url"].rsplit("/", 1)[0],
                        "env",
                        "NM2_NATIVE_OWNER",
                    )
                elif reason == "binary":
                    n.binary.write_bytes(b"changed disposable binary; must never launch")
                elif reason == "auxiliary":
                    gate.case["setup"][0]["request"]["url"] += "/changed"
                else:
                    time.sleep(max(0, expiry - time.time()) + 0.2)
            return original()

        monkeypatch.setattr(n.runner.config, "tool_environment", preparation)
        if reason.startswith("permit_"):
            from vardrrunner.windows_job import WindowsJob

            original_init = WindowsJob.__init__

            def delayed_permit(self, cmd, environment, permit=None):
                def check():
                    if permit:
                        permit()
                    changed.append(True)
                    if reason == "permit_stop":
                        operator.client.post("/native/stop", json={})
                    else:
                        time.sleep(max(0, expiry - time.time()) + 0.2)

                return original_init(self, cmd, environment, check)

            monkeypatch.setattr(WindowsJob, "__init__", delayed_permit)
        folder = tmp_path / "denied"
        folder.mkdir()
        from vardrrunner.authorization.codec import AuthorizationError
        from vardrrunner.credential_grants import GrantError

        with (
            n.runner.observe_process(pids.append),
            pytest.raises(
                (AuthorizationError, GrantError, n.control.ExecutionStopped, n.runner.ToolTimeout)
            ),
        ):
            gate.execute(folder)
        assert changed and not pids and not n.seen
    assert_retained(n)
    proof(n, "preparation_" + reason, {"native_pids": pids, "zero_target_contacts": True})
