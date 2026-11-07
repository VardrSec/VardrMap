"""Unregistered managed HTTP adapter; real auth and disposable database only."""

import asyncio
import copy
import hashlib
import json
import logging
from datetime import timedelta
from types import SimpleNamespace

import execution_control as control
import local_auth
import managed_http as boundary
import pytest
from db import get_db
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from managed_issuance import Issuer
from managed_wire import digest
from models import (
    ApiKey,
    AuthorizationTestCase,
    Engagement,
    JobExecution,
    LocalCredential,
    ManagedApproval,
    ManagedContract,
    ManagedEnrollment,
    ScanJob,
    User,
)
from routers.local_auth import router as local_router
from sqlalchemy.orm import Session
from starlette.requests import Request
from tests.test_managed_issuance import KEY, NOW, RUNNER, mint_token, register, signed
from tests.test_managed_issuance import specimen as specimen

ORIGIN = "https://map.synthetic.test"
PATH = "/jobs/job-1/managed"
PASSWORD = "public synthetic operator password 123!"


@pytest.fixture
def http(specimen, monkeypatch):
    s = specimen
    monkeypatch.setattr(control, "now", lambda: s["wall"][0].replace(tzinfo=None))
    monkeypatch.setenv("VARDRMAP_AUTH_METHODS", "github,local")
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    s["service"] = Issuer(
        ORIGIN, s["wire"], clock=lambda: s["wall"][0], monotonic=lambda: s["ticks"][0]
    )
    s["db"].get(ManagedEnrollment, "enrollment-1").origin = ORIGIN
    s["db"].commit()
    context = s["review"]["context"]
    s["review"] = s["service"].review(
        s["db"],
        s["owner"],
        job_id="job-1",
        enrollment_id="enrollment-1",
        authorization_id="auth-1",
        plan=s["plan"],
        expires_at=context["expires_at"],
        max_executions=context["max_executions"],
        max_duration_seconds=context["max_duration_seconds"],
        max_artifact_bytes=context["max_artifact_bytes"],
        credential_grants=context["credential_grants"],
    )
    s["approval"] = signed(s["review"]["context"])
    register(s)
    s["body"].origin = ORIGIN
    app = FastAPI()
    app.include_router(local_router)
    app.include_router(boundary.build_managed_router(s["service"]))

    def database():
        with Session(s["engine"]) as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app, base_url=ORIGIN) as client:
        yield SimpleNamespace(
            s=s,
            client=client,
            app=app,
            headers={"Authorization": "Bearer " + KEY},
            body=s["body"].model_dump(mode="json"),
            pending={"origin": ORIGIN, "runner_id": RUNNER},
        )


def facts(h):
    with Session(h.s["engine"]) as db:
        job, engagement = db.get(ScanJob, "job-1"), db.get(Engagement, "eng-1")
        return (
            job.status,
            job.case_snapshot,
            engagement.targets_spent,
            engagement.duration_allocated,
            db.query(ManagedContract).count(),
            db.query(JobExecution).count(),
            db.get(ManagedApproval, "managed-fixture:fixture-approval").issued,
        )


def post(h, suffix, body=None, headers=None):
    return h.client.post(
        PATH + suffix,
        json=h.body if body is None else body,
        headers=h.headers if headers is None else headers,
    )


def claimed(h):
    reply = post(h, "/claim")
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    with Session(h.s["engine"]) as db:
        contract = db.query(ManagedContract).one()
        owned = {
            **h.pending,
            "token": payload["execution_control"]["token"],
            "contract_id": contract.id,
            "attempt_id": contract.attempt_id,
            "fence": contract.fence,
        }
    return payload, owned


def test_assigned_signed_inventory_is_discovery_without_execution_or_budget_mutation(
    http,
):
    h = http
    before = facts(h)
    reply = h.client.post(boundary.PENDING_PATH, json=h.pending, headers=h.headers)
    assert reply.status_code == 200 and reply.headers["Cache-Control"] == "no-store"
    body = reply.json()
    assert body["next_after"] is None and len(body["jobs"]) == 1
    job = body["jobs"][0]
    assert job["id"] == "job-1" and job["plan"] == h.s["plan"]
    assert job["config"]["test_case"] == h.s["review"]["case"]
    assert '"token"' not in reply.text and KEY not in reply.text and facts(h) == before


@pytest.mark.parametrize(
    "change",
    [
        "unapproved",
        "revoked",
        "ordinary",
        "finished",
        "foreign_engagement",
        "expired",
        "signature",
        "other_enrollment",
    ],
)
def test_inventory_never_offers_unassigned_unsigned_or_revoked_work(http, change):
    h = http
    with Session(h.s["engine"]) as db:
        job = db.get(ScanJob, "job-1")
        approval = db.query(ManagedApproval).one()
        if change == "unapproved":
            job.managed_approval_id = None
        elif change == "revoked":
            approval.revoked = True
        elif change == "ordinary":
            job.authorization_contract_required = False
        elif change == "finished":
            job.status = "done"
        elif change == "foreign_engagement":
            db.get(Engagement, "eng-1").owner_github_id = "other"
        elif change == "signature":
            approval.envelope = {**approval.envelope, "signature": "A" * 86}
        elif change == "other_enrollment":
            enrollment = db.get(ManagedEnrollment, "enrollment-1")
            db.add(
                ManagedEnrollment(
                    id="enrollment-2",
                    api_key_id=enrollment.api_key_id,
                    owner=enrollment.owner,
                    principal_hash=enrollment.principal_hash,
                    origin=enrollment.origin,
                    runner_id="00000000-0000-0000-0000-000000000099",
                    revision=1,
                    revoked=False,
                )
            )
            approval.enrollment_id = "enrollment-2"
        else:
            h.s["wall"][0] = NOW + timedelta(minutes=2)
        db.commit()
    before = facts(h)
    reply = h.client.post(boundary.PENDING_PATH, json=h.pending, headers=h.headers)
    assert reply.status_code == 200 and reply.json() == {"jobs": [], "next_after": None}
    assert facts(h) == before


@pytest.mark.parametrize("limit", [0, 21, True])
def test_inventory_refuses_unbounded_or_coerced_page_sizes(http, limit):
    h = http
    before = facts(h)
    reply = h.client.post(
        boundary.PENDING_PATH, json={**h.pending, "limit": limit}, headers=h.headers
    )
    assert reply.status_code == 422 and facts(h) == before


def test_inventory_is_bounded_and_cursor_does_not_reoffer_the_previous_job(http):
    h = http
    with Session(h.s["engine"]) as db:
        original = db.get(ScanJob, "job-1")
        db.add(
            ScanJob(
                id="job-2",
                program_id=original.program_id,
                owner_github_id="owner-1",
                tool_type=original.tool_type,
                target_source="scope",
                config=original.config,
                authorization_contract_required=True,
                status="pending",
            )
        )
        db.commit()
        args = dict(
            job_id="job-2",
            enrollment_id="enrollment-1",
            authorization_id="auth-1",
            plan=h.s["plan"],
        )
        context = h.s["review"]["context"]
        review = h.s["service"].review(
            db,
            h.s["owner"],
            **args,
            **{
                k: context[k]
                for k in (
                    "expires_at",
                    "max_executions",
                    "max_duration_seconds",
                    "max_artifact_bytes",
                    "credential_grants",
                )
            },
        )
        h.s["service"].register(
            db, h.s["owner"], **args, approval=signed(review["context"], "second")
        )
    first = h.client.post(
        boundary.PENDING_PATH, json={**h.pending, "limit": 1}, headers=h.headers
    ).json()
    assert [j["id"] for j in first["jobs"]] == ["job-1"] and first[
        "next_after"
    ] == "job-1"
    second = h.client.post(
        boundary.PENDING_PATH,
        json={**h.pending, "limit": 1, "after": first["next_after"]},
        headers=h.headers,
    ).json()
    assert [j["id"] for j in second["jobs"]] == ["job-2"] and second[
        "next_after"
    ] is None


def test_claim_returns_the_frozen_case_and_cannot_spend_twice(http, monkeypatch):
    h = http
    original = h.s["service"].claim
    expected = copy.deepcopy(h.s["review"]["case"])

    def edit_after_commit(*args, **kwargs):
        reply = original(*args, **kwargs)
        with Session(h.s["engine"]) as db:
            changed = copy.deepcopy(db.get(AuthorizationTestCase, "case-1").spec)
            changed["request"]["url"] = "https://api.example.test/later-edit"
            db.get(AuthorizationTestCase, "case-1").spec = changed
            db.commit()
        return reply

    monkeypatch.setattr(h.s["service"], "claim", edit_after_commit)
    payload, _ = claimed(h)
    assert payload["config"]["test_case"] == expected
    before = facts(h)
    assert before[2:] == (1, 30, 1, 1, 1)
    assert post(h, "/claim").status_code == 409 and facts(h) == before


def test_case_changed_before_claim_is_refused_without_spend(http):
    h = http
    with Session(h.s["engine"]) as db:
        changed = copy.deepcopy(db.get(AuthorizationTestCase, "case-1").spec)
        changed["request"]["url"] = "https://api.example.test/unapproved-edit"
        db.get(AuthorizationTestCase, "case-1").spec = changed
        db.commit()
    before = facts(h)
    assert post(h, "/claim").status_code == 409 and facts(h) == before


def test_current_does_not_renew_refresh_renews_and_consumption_is_one_shot(http):
    h = http
    payload, owned = claimed(h)
    with Session(h.s["engine"]) as db:
        expires = db.get(JobExecution, "job-1").expires_at
    h.s["wall"][0] += timedelta(seconds=1)
    h.s["ticks"][0] += 1
    current = post(h, "/current", owned)
    assert current.status_code == 200 and "lease_seconds" not in current.json()
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == expires
    renewed = post(h, "/refresh", owned)
    assert renewed.status_code == 200 and renewed.json()["action"] == "continue"
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at > expires
    consumption = {
        **owned,
        "contract_sha256": digest(payload["managed_authorization"]["contract"]),
    }
    reply = post(h, "/consume", consumption)
    assert reply.status_code == 200 and reply.json()["consumed"] is True
    assert post(h, "/consume", consumption).status_code == 409
    assert facts(h)[2:] == (1, 30, 1, 1, 1)


@pytest.mark.parametrize("route", ["pending", "claim"])
@pytest.mark.parametrize(
    "kind,status",
    [
        ("missing", 401),
        ("invalid", 401),
        ("foreign", 404),
        ("other_key", 409),
        ("revoked", 409),
        ("deleted", 401),
        ("jwt", 409),
    ],
)
def test_real_authentication_never_uses_payload_identity_as_a_principal(
    http, route, kind, status
):
    h = http
    headers = dict(h.headers)
    with Session(h.s["engine"]) as db:
        if kind == "missing":
            headers = {}
        elif kind == "invalid":
            headers = {"Authorization": "Bearer vmap_synthetic_do_not_echo"}
        elif kind in {"foreign", "other_key"}:
            owner = "other" if kind == "foreign" else "owner-1"
            if kind == "foreign":
                db.add(User(github_id=owner, username=owner))
                db.flush()
            key = "vmap_other_public_disposable_key"
            db.add(
                ApiKey(
                    github_id=owner,
                    key_hash=hashlib.sha256(key.encode()).hexdigest(),
                    scope="runner",
                )
            )
            headers = {"Authorization": "Bearer " + key}
            if route == "pending" and kind == "other_key":
                status = 404
        elif kind == "revoked":
            db.get(ManagedEnrollment, "enrollment-1").revoked = True
        elif kind == "deleted":
            db.delete(db.get(ApiKey, "key-1"))
        else:
            headers = {"Authorization": "Bearer " + mint_token("owner-1")}
            if route == "pending":
                status = 403
        db.commit()
    before = facts(h)
    reply = (
        h.client.post(boundary.PENDING_PATH, json=h.pending, headers=headers)
        if route == "pending"
        else post(h, "/claim", headers=headers)
    )
    assert reply.status_code == status and reply.json() == {
        "detail": "managed_request_refused"
    }
    assert reply.headers["Cache-Control"] == "no-store" and facts(h) == before
    assert "synthetic_do_not_echo" not in reply.text


@pytest.mark.parametrize("csrf", ["missing", "wrong", "valid"])
def test_local_owner_session_requires_csrf_and_still_cannot_claim_as_a_runner(
    http, csrf
):
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
    login = h.client.post(
        "/auth/local/login",
        json={"username": "operator", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200
    session = h.client.get("/auth/local/session").json()
    headers = {"Origin": ORIGIN}
    if csrf != "missing":
        headers["X-CSRF-Token"] = session["csrfToken"] if csrf == "valid" else "0" * 64
    before = facts(h)
    reply = post(h, "/claim", headers=headers)
    assert reply.status_code == (409 if csrf == "valid" else 403)
    assert reply.json() == {"detail": "managed_request_refused"} and facts(h) == before


@pytest.mark.parametrize(
    "kind,status",
    [
        ("duplicate", 422),
        ("utf8", 422),
        ("nonfinite", 422),
        ("extra", 422),
        ("bool_duration", 422),
        ("bad_uuid", 422),
        ("length", 413),
        ("stream", 413),
        ("encoding", 415),
        ("type", 415),
        ("http", 403),
    ],
)
def test_strict_bounded_requests_fail_before_claim_without_echo(http, kind, status):
    h = http
    headers = {**h.headers, "Content-Type": "application/json"}
    data = json.dumps(h.body).encode()
    path = PATH + "/claim"
    if kind == "duplicate":
        data = b'{"token":"synthetic_do_not_echo","token":1}'
    elif kind == "utf8":
        data = b"\xff"
    elif kind == "nonfinite":
        data = b'{"duration_seconds":1e999}'
    elif kind in {"extra", "bool_duration", "bad_uuid"}:
        body = dict(h.body)
        body[
            {
                "extra": "principal_hash",
                "bool_duration": "duration_seconds",
                "bad_uuid": "runner_id",
            }[kind]
        ] = True if kind == "bool_duration" else "synthetic_do_not_echo"
        data = json.dumps(body).encode()
    elif kind == "length":
        headers["Content-Length"] = "9000"
    elif kind == "stream":
        data = iter([b"x" * 8192, b"x"])
    elif kind == "encoding":
        headers["Content-Encoding"] = "gzip"
    elif kind == "type":
        headers["Content-Type"] = "text/plain"
    else:
        path = "http://map.synthetic.test" + path
    before = facts(h)
    reply = h.client.post(path, content=data, headers=headers)
    assert reply.status_code == status and reply.json() == {
        "detail": "managed_request_refused"
    }
    assert "synthetic_do_not_echo" not in reply.text and facts(h) == before


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("fence", True, 422),
        ("token", "wrong", 422),
        ("runner_id", "00000000-0000-0000-0000-000000000099", 404),
        ("contract_id", "00000000-0000-0000-0000-000000000099", 409),
    ],
)
def test_control_refuses_wrong_or_coerced_ownership_without_renewal(
    http, field, value, status
):
    h = http
    _, owned = claimed(h)
    before = facts(h)
    with Session(h.s["engine"]) as db:
        expires = db.get(JobExecution, "job-1").expires_at
    reply = post(h, "/refresh", {**owned, field: value})
    assert reply.status_code == status and facts(h) == before
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == expires


def test_factory_stays_unregistered_and_offers_no_bootstrap_approval_or_finalization(
    http,
):
    from main import app

    paths = {
        route.path for route in boundary.build_managed_router(http.s["service"]).routes
    }
    assert paths == {
        boundary.PENDING_PATH,
        *(
            boundary.JOB_PATH + "/" + name
            for name in ("claim", "current", "refresh", "consume")
        ),
    }
    assert paths.isdisjoint(app.openapi()["paths"])


@pytest.mark.parametrize(
    "failure,status",
    [("timeout", 408), ("disconnect", 400), ("exception", 503), ("reply_size", 503)],
)
def test_transport_and_failure_responses_are_bounded_and_secret_free(
    http, monkeypatch, failure, status
):
    h = http
    if failure == "exception":

        def fail(*args, **kwargs):
            raise OSError("synthetic_do_not_echo")

        monkeypatch.setattr(h.s["service"], "claim", fail)
    elif failure == "reply_size":
        monkeypatch.setattr(boundary, "RESPONSE_MAX_BYTES", 1)
    monkeypatch.setattr(boundary, "BODY_TIMEOUT_SECONDS", 0.01)

    async def receive():
        if failure == "timeout":
            await asyncio.sleep(1)
        if failure == "disconnect":
            return {"type": "http.disconnect"}
        return {
            "type": "http.request",
            "body": json.dumps(h.body).encode(),
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": PATH + "/claim",
            "server": ("map.synthetic.test", 443),
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", ("Bearer " + KEY).encode()),
            ],
        },
        receive=receive,
    )
    router = boundary.build_managed_router(h.s["service"])
    with Session(h.s["engine"]) as db:
        reply = asyncio.run(router.routes[1].endpoint("job-1", request, db=db))
    assert (
        reply.status_code == status
        and "synthetic_do_not_echo" not in reply.body.decode()
    )
    assert reply.headers["Cache-Control"] == "no-store"
    if failure == "reply_size":
        # A committed claim whose response cannot be returned remains spent,
        # never refunded/replayed as a second physical attempt.
        assert facts(h)[2:] == (1, 30, 1, 1, 1)
        assert post(h, "/claim").status_code == 409


def test_duration_exhaustion_marker_requires_exact_managed_allocator_refusal(http, caplog):
    with Session(http.s["engine"]) as db:
        engagement = db.get(Engagement, "eng-1")
        engagement.duration_allocated = engagement.duration_limit
        db.commit()
    before = facts(http)
    assert before == ("pending", None, 0, 120, 0, 0, 0)
    with caplog.at_level(logging.WARNING, logger=boundary.__name__):
        reply = post(http, "/claim")
    assert reply.status_code == 409
    assert reply.json() == {"detail": "managed_request_refused"}
    assert reply.headers["Cache-Control"] == "no-store"
    assert facts(http) == before
    assert [
        (record.msg, record.args, record.exc_info)
        for record in caplog.records
        if record.name == boundary.__name__
    ] == [("managed_claim_duration_exhausted", (), None)]


@pytest.mark.parametrize("denial", ["target", "same_detail_generic"])
def test_duration_exhaustion_marker_excludes_other_managed_conflicts(
    http, caplog, monkeypatch, denial
):
    if denial == "target":
        with Session(http.s["engine"]) as db:
            engagement = db.get(Engagement, "eng-1")
            engagement.targets_spent = engagement.target_limit
            db.commit()
    else:
        def generic(*args, **kwargs):
            raise HTTPException(409, "engagement duration allocation exhausted")

        monkeypatch.setattr("duration_budget.allocate", generic)
    before = facts(http)
    with caplog.at_level(logging.WARNING, logger=boundary.__name__):
        reply = post(http, "/claim")
    assert reply.status_code == 409
    assert reply.json() == {"detail": "managed_request_refused"}
    assert reply.headers["Cache-Control"] == "no-store"
    assert facts(http) == before
    assert not any(record.name == boundary.__name__ for record in caplog.records)
