"""Real ASGI owned receipts; synthetic assertions, never process attestation."""

import asyncio
import copy
import hashlib
import json
from datetime import timedelta

import local_auth
import managed_receipt_http as boundary
import pytest
from managed_results import Results
from managed_wire import digest
from models import (
    ApiKey,
    Engagement,
    Evidence,
    JobExecution,
    JobResultReceipt,
    LocalCredential,
    ManagedApproval,
    ManagedContract,
    ManagedResult,
    ManagedStop,
    ScanItem,
    ScanJob,
    User,
)
from sqlalchemy import event
from sqlalchemy.orm import Session
from starlette.requests import Request
from tests.test_managed_http_boundary import (
    ORIGIN,
    PASSWORD,
    claimed,
    post as control_post,
)
from tests import test_managed_http_boundary as runtime
from tests.test_managed_issuance import KEY, mint_token
from tests.test_managed_issuance import specimen as specimen

PATH = "/jobs/job-1/managed"
PRIVATE = "private-http-receipt-fixture-654321"
runtime_http = runtime.http


@pytest.fixture
def http(runtime_http):
    h = runtime_http
    h.results = Results(h.s["service"])
    h.app.include_router(boundary.build_receipt_router(h.results))
    payload, owned = claimed(h)
    h.owned = {
        **owned,
        "contract_sha256": digest(payload["managed_authorization"]["contract"]),
    }
    assert control_post(h, "/consume", h.owned).status_code == 200
    case = payload["config"]["test_case"]
    h.raw = {
        "test_case_id": case["id"],
        "case_hash": h.s["plan"]["case_hash"],
        "executions": [
            {
                "identity_id": case["identities"][0]["id"],
                "status_code": 200,
                "observed_outcome": "allow",
                "headers": {"Authorization": "Bearer " + PRIVATE},
            }
        ],
        "findings": [
            {
                "severity": "high",
                "message": "synthetic candidate",
                "category": "fixture",
            }
        ],
    }
    h.stop = {
        **h.owned,
        "outcome": "cancelled",
        "cause": "local_emergency_stop",
        "termination_confirmed": True,
    }
    return h


def artifact(h, raw=None):
    text = json.dumps(h.raw if raw is None else raw)
    return {
        **h.owned,
        "artifact": text,
        "artifact_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def finish_body(h, ack, outcome="completed"):
    return {
        **h.owned,
        "receipt_sha256": ack["receipt_sha256"],
        "outcome": outcome,
        "termination_confirmed": True,
    }


def post(h, suffix, body=None, headers=None):
    return h.client.post(
        PATH + suffix,
        json=artifact(h) if body is None else body,
        headers=h.headers if headers is None else headers,
    )


def state(h):
    with Session(h.s["engine"]) as db:
        job, execution, engagement = (
            db.get(ScanJob, "job-1"),
            db.get(JobExecution, "job-1"),
            db.get(Engagement, "eng-1"),
        )
        return {
            "job": job.status,
            "execution": execution.state,
            "capacity": execution.capacity_reserved,
            "targets": engagement.targets_spent,
            "duration": engagement.duration_allocated,
            "issued": db.query(ManagedApproval).one().issued,
            "consumed": db.query(ManagedContract).one().consumed,
            "results": [
                (r.receipt_sha256, r.artifact_sha256, r.outcome)
                for r in db.query(ManagedResult).all()
            ],
            "stops": [
                (r.receipt_sha256, r.outcome, r.cause)
                for r in db.query(ManagedStop).all()
            ],
            "evidence": db.query(Evidence).count(),
            "candidates": db.query(ScanItem).count(),
            "legacy_receipts": db.query(JobResultReceipt).count(),
        }


def assert_spent(h):
    values = state(h)
    assert (
        values["targets"],
        values["duration"],
        values["issued"],
        values["consumed"],
    ) == (1, 30, 1, True)
    return values


def test_owned_result_retention_completion_and_exact_replays_are_atomic(http):
    h = http
    accepted = post(h, "/result")
    assert (
        accepted.status_code == 200 and accepted.headers["Cache-Control"] == "no-store"
    )
    ack = accepted.json()
    assert ack["artifact_sha256"] == artifact(h)["artifact_sha256"]
    assert ack["case_sha256"] == h.s["plan"]["case_hash"]
    before = assert_spent(h)
    assert (
        before["capacity"]
        and before["evidence"] == before["candidates"] == before["legacy_receipts"] == 1
    )
    assert post(h, "/result").json() == ack and state(h) == before
    assert PRIVATE not in accepted.text and KEY not in accepted.text
    with Session(h.s["engine"]) as db:
        assert PRIVATE not in db.query(Evidence).one().body
        assert db.query(ScanItem).one().status == "new"
    done = post(h, "/finish", finish_body(h, ack))
    assert done.status_code == 200 and done.json()["capacity_reserved"] is False
    terminal = assert_spent(h)
    assert terminal["job"] == "done" and not terminal["capacity"]
    assert post(h, "/finish", finish_body(h, ack)).json() == done.json()
    assert post(h, "/finish", finish_body(h, ack, "failed")).status_code == 409
    assert state(h) == terminal


def test_changed_result_cannot_replace_retained_evidence_or_receipt(http):
    h = http
    assert post(h, "/result").status_code == 200
    before = state(h)
    changed = copy.deepcopy(h.raw)
    changed["findings"][0]["message"] = "different candidate"
    assert post(h, "/result", artifact(h, changed)).status_code == 409
    assert state(h) == before


def test_known_stop_report_and_inspection_never_renew_or_refund(http):
    h = http
    with Session(h.s["engine"]) as db:
        expires = db.get(JobExecution, "job-1").expires_at
    before = assert_spent(h)
    observed = post(h, "/stop-status", h.owned)
    assert observed.status_code == 200 and observed.json()["stop"] is None
    assert observed.json()["capacity_reserved"] is True and state(h) == before
    h.s["wall"][0] += timedelta(minutes=2)
    stopped = post(h, "/stopped", h.stop)
    assert stopped.status_code == 200 and stopped.json()["outcome"] == "cancelled"
    assert stopped.json()["capacity_reserved"] is False
    terminal = assert_spent(h)
    assert terminal["job"] == "failed" and len(terminal["stops"]) == 1
    assert terminal["results"] == [] and terminal["evidence"] == 0
    assert post(h, "/stopped", h.stop).json() == stopped.json()
    assert post(h, "/stop-status", h.owned).json()["stop"] == stopped.json()
    assert state(h) == terminal
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == expires


@pytest.mark.parametrize("denial", ["expired", "revoked"])
def test_historical_evidence_survives_but_success_requires_live_authority(http, denial):
    h = http
    if denial == "expired":
        h.s["wall"][0] += timedelta(minutes=2)
    else:
        with Session(h.s["engine"]) as db:
            db.query(ManagedApproval).one().revoked = True
            db.commit()
    accepted = post(h, "/result")
    assert accepted.status_code == 200
    before = state(h)
    assert post(h, "/finish", finish_body(h, accepted.json())).status_code == 409
    assert state(h) == before and before["capacity"]
    failed = post(h, "/finish", finish_body(h, accepted.json(), "failed"))
    assert failed.status_code == 200 and failed.json()["outcome"] == "failed"
    assert not assert_spent(h)["capacity"]


def test_stop_cannot_overwrite_an_existing_result_protocol(http):
    h = http
    assert post(h, "/result").status_code == 200
    before = state(h)
    assert post(h, "/stopped", h.stop).status_code == 409
    assert state(h) == before and before["capacity"]


@pytest.mark.parametrize("route", ["result", "finish", "stopped", "stop-status"])
@pytest.mark.parametrize(
    "kind,status",
    [
        ("missing", 401),
        ("foreign", 404),
        ("other_key", 404),
        ("deleted", 401),
        ("jwt", 403),
    ],
)
def test_all_receipt_operations_authenticate_the_original_key_and_ownership(
    http, route, kind, status
):
    h = http
    headers = {}
    with Session(h.s["engine"]) as db:
        if kind in {"foreign", "other_key"}:
            owner = "other" if kind == "foreign" else "owner-1"
            if kind == "foreign":
                db.add(User(github_id=owner, username=owner))
                db.flush()
            key = "vmap_other_public_receipt_key"
            db.add(
                ApiKey(
                    github_id=owner,
                    key_hash=hashlib.sha256(key.encode()).hexdigest(),
                    scope="runner",
                )
            )
            headers = {"Authorization": "Bearer " + key}
        elif kind == "deleted":
            db.delete(db.get(ApiKey, "key-1"))
            headers = h.headers
        elif kind == "jwt":
            headers = {"Authorization": "Bearer " + mint_token("owner-1")}
        db.commit()
    body = {
        "result": artifact(h),
        "finish": finish_body(h, {"receipt_sha256": "0" * 64}),
        "stopped": h.stop,
        "stop-status": h.owned,
    }[route]
    before = state(h)
    reply = post(h, "/" + route, body, headers)
    assert reply.status_code == status and reply.json() == {
        "detail": "managed_receipt_refused"
    }
    assert reply.headers["Cache-Control"] == "no-store" and state(h) == before


@pytest.mark.parametrize("csrf", ["missing", "wrong", "valid"])
def test_local_owner_cookie_keeps_csrf_and_cannot_replace_the_runner_key(http, csrf):
    h = http
    with Session(h.s["engine"]) as db:
        db.add(
            LocalCredential(
                user_id="owner-1",
                username="operator",
                password_hash=local_auth.PASSWORD_HASHER.hash(PASSWORD),
            )
        )
        db.commit()
    assert (
        h.client.post(
            "/auth/local/login",
            json={"username": "operator", "password": PASSWORD},
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )
    session = h.client.get("/auth/local/session").json()
    headers = {"Origin": ORIGIN}
    if csrf != "missing":
        headers["X-CSRF-Token"] = session["csrfToken"] if csrf == "valid" else "0" * 64
    before = state(h)
    reply = post(h, "/stopped", h.stop, headers)
    assert reply.status_code == 403 and state(h) == before
    assert reply.json() == {"detail": "managed_receipt_refused"}


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("fence", True, 422),
        ("runner_id", "00000000-0000-0000-0000-000000000099", 404),
        ("contract_id", "00000000-0000-0000-0000-000000000099", 409),
        ("contract_sha256", "0" * 64, 409),
        ("token", "x" * 43, 404),
    ],
)
@pytest.mark.parametrize("route", ["result", "stopped"])
def test_foreign_or_coerced_binding_cannot_store_or_release(
    http, field, value, status, route
):
    h = http
    before = state(h)
    body = artifact(h) if route == "result" else h.stop
    reply = post(h, "/" + route, {**body, field: value})
    assert reply.status_code == status and state(h) == before


@pytest.mark.parametrize(
    "kind,status",
    [
        ("length", 413),
        ("stream", 413),
        ("control_length", 413),
        ("artifact_chars", 422),
        ("artifact_bytes", 409),
        ("inner_duplicate", 409),
        ("inner_case", 409),
        ("unknown_cause", 409),
        ("unconfirmed", 409),
        ("coerced", 422),
        ("completed_stop", 409),
        ("utf8", 422),
        ("duplicate", 422),
        ("nonfinite", 422),
        ("extra", 422),
        ("http", 403),
        ("encoding", 415),
        ("media", 415),
    ],
)
def test_strict_transport_artifact_and_known_stop_bounds_are_fail_closed(
    http, kind, status
):
    h = http
    headers = {**h.headers, "Content-Type": "application/json"}
    path, body = PATH + "/result", artifact(h)
    if kind in {
        "control_length",
        "unknown_cause",
        "unconfirmed",
        "coerced",
        "completed_stop",
    }:
        path, body = PATH + "/stopped", dict(h.stop)
        if kind == "control_length":
            headers["Content-Length"] = "9000"
        elif kind == "unknown_cause":
            body["cause"] = "synthetic_do_not_echo"
        elif kind == "completed_stop":
            body["outcome"] = "completed"
        else:
            body["termination_confirmed"] = 1 if kind == "coerced" else False
    elif kind == "length":
        headers["Content-Length"] = str(boundary.RESULT_BODY_MAX_BYTES + 1)
    elif kind in {"artifact_chars", "artifact_bytes", "inner_duplicate"}:
        text = {
            "artifact_chars": "x" * 512001,
            "artifact_bytes": "é" * 256001,
            "inner_duplicate": '{"case_hash":"a","case_hash":"b"}',
        }[kind]
        body.update(
            artifact=text, artifact_sha256=hashlib.sha256(text.encode()).hexdigest()
        )
    elif kind == "inner_case":
        body = artifact(h, {**h.raw, "case_hash": "0" * 64})
    elif kind == "extra":
        body["principal_hash"] = "synthetic_do_not_echo"
    elif kind == "http":
        path = "http://map.synthetic.test" + path
    elif kind == "encoding":
        headers["Content-Encoding"] = "gzip"
    elif kind == "media":
        headers["Content-Type"] = "text/plain"
    data = json.dumps(body, ensure_ascii=False).encode()
    if kind == "stream":
        data = iter([b"x" * boundary.RESULT_BODY_MAX_BYTES, b"x"])
    elif kind == "utf8":
        data = b"\xff"
    elif kind == "duplicate":
        data = b'{"token":"synthetic_do_not_echo","token":1}'
    elif kind == "nonfinite":
        data = b'{"artifact":1e999}'
    before = state(h)
    reply = h.client.post(path, content=data, headers=headers)
    assert reply.status_code == status and reply.json() == {
        "detail": "managed_receipt_refused"
    }
    assert "synthetic_do_not_echo" not in reply.text and state(h) == before


def test_database_failure_rolls_back_evidence_and_returns_no_raw_error(http):
    h = http
    before = state(h)

    def fault(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO managed_results"):
            raise RuntimeError("synthetic_do_not_echo")

    event.listen(h.s["engine"], "after_cursor_execute", fault)
    try:
        reply = post(h, "/result")
    finally:
        event.remove(h.s["engine"], "after_cursor_execute", fault)
    assert reply.status_code == 503 and "synthetic_do_not_echo" not in reply.text
    assert state(h) == before


def test_oversized_reply_does_not_undo_a_committed_result_or_release_capacity(
    http, monkeypatch
):
    h = http
    monkeypatch.setattr(boundary, "RESPONSE_MAX_BYTES", 1)
    reply = post(h, "/result")
    assert reply.status_code == 503 and reply.json() == {
        "detail": "managed_receipt_refused"
    }
    retained = assert_spent(h)
    assert len(retained["results"]) == 1 and retained["capacity"]
    monkeypatch.setattr(boundary, "RESPONSE_MAX_BYTES", 16384)
    assert post(h, "/result").status_code == 200 and state(h) == retained


@pytest.mark.parametrize("failure,status", [("timeout", 408), ("disconnect", 400)])
def test_body_read_has_a_total_deadline_and_no_partial_receipt(
    http, monkeypatch, failure, status
):
    h = http
    monkeypatch.setattr(boundary, "BODY_TIMEOUT_SECONDS", 0.01)

    async def receive():
        if failure == "timeout":
            await asyncio.sleep(1)
        return {"type": "http.disconnect"}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": PATH + "/result",
            "server": ("map.synthetic.test", 443),
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    before = state(h)
    router = boundary.build_receipt_router(h.results)
    with Session(h.s["engine"]) as db:
        reply = asyncio.run(router.routes[0].endpoint("job-1", request, db=db))
    assert reply.status_code == status and state(h) == before


def test_receipt_factory_is_unregistered_and_has_no_execution_or_bootstrap_routes(http):
    from main import app

    paths = {route.path for route in boundary.build_receipt_router(http.results).routes}
    assert paths == {
        boundary.JOB_PATH + "/" + name
        for name in ("result", "finish", "stopped", "stop-status")
    }
    assert paths.isdisjoint(app.openapi()["paths"])
