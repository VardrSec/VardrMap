"""Human-owned approval receipts over ASGI; only public fixture signing seeds."""

import asyncio
import copy
import json
from datetime import timedelta

import local_auth
import managed_approval_http as boundary
import managed_enrollment as enrollment
import pytest
from models import (
    ApiKey,
    AuthorizationTestCase,
    Engagement,
    JobExecution,
    LocalCredential,
    LocalSession,
    ManagedApproval,
    ManagedContract,
    ScanJob,
)
from sqlalchemy.orm import Session
from starlette.requests import Request
from tests import test_managed_http_boundary as runtime
from tests.test_managed_http_boundary import ORIGIN, PASSWORD, claimed
from tests.test_managed_issuance import KEY, mint_token, signed
from tests.test_managed_issuance import specimen as specimen

runtime_http = runtime.http
PATH = "/jobs/job-1/managed/approval"


@pytest.fixture
def http(runtime_http):
    h = runtime_http
    h.app.include_router(boundary.build_approval_router(h.s["service"]))
    with Session(h.s["engine"]) as db:
        db.get(ScanJob, "job-1").managed_approval_id = None
        db.query(ManagedApproval).delete()
        db.commit()
    h.owner_headers = {"Authorization": "Bearer " + mint_token("owner-1")}
    h.selection = {
        "enrollment_id": "enrollment-1",
        "authorization_id": "auth-1",
        "plan": h.s["plan"],
    }
    context = h.s["review"]["context"]
    h.review = {
        **h.selection,
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
    }
    return h


def post(h, operation, body=None, headers=None):
    return h.client.post(
        PATH + "/" + operation,
        json=h.review if body is None else body,
        headers=h.owner_headers if headers is None else headers,
    )


def register(h, headers=None):
    review = post(h, "review", headers=headers)
    assert review.status_code == 200, review.text
    body = {**h.selection, "approval": signed(review.json()["context"])}
    reply = post(h, "register", body, headers)
    assert reply.status_code == 200, reply.text
    return reply, body


def state(h):
    with Session(h.s["engine"]) as db:
        job, engagement = db.get(ScanJob, "job-1"), db.get(Engagement, "eng-1")
        return (
            job.status,
            job.managed_approval_id,
            job.case_snapshot,
            engagement.targets_spent,
            engagement.duration_allocated,
            db.query(JobExecution).count(),
            db.query(ManagedContract).count(),
            [
                (r.id, r.issued, r.revoked, r.envelope)
                for r in db.query(ManagedApproval)
            ],
        )


def test_review_is_unsigned_and_registration_needs_the_separately_signed_exact_context(
    http,
):
    h = http
    before = state(h)
    review = post(h, "review")
    assert review.status_code == 200 and review.headers["Cache-Control"] == "no-store"
    assert review.json()["context"] == h.s["review"]["context"]
    assert "signature" not in review.json() and "contract" not in review.json()
    assert state(h) == before
    accepted, body = register(h)
    assert accepted.json() == {"approval_record_id": "managed-fixture:fixture-approval"}
    registered = state(h)
    assert registered[0] == "pending" and registered[3:7] == (0, 0, 0, 0)
    assert (
        post(h, "register", body).json() == accepted.json() and state(h) == registered
    )
    claimed(h)
    spent = state(h)
    assert spent[3:7] == (1, 30, 1, 1) and spent[7][0][1] == 1
    assert post(h, "register", body).json() == accepted.json() and state(h) == spent
    revoked = post(h, "revoke", {})
    assert revoked.status_code == 200 and revoked.json() == {
        "job_id": "job-1",
        "revoked": True,
    }
    terminal = state(h)
    assert terminal[7][0][1:3] == (1, True)
    assert post(h, "revoke", {}).json() == revoked.json() and state(h) == terminal
    assert post(h, "register", body).status_code == 409 and state(h) == terminal


def test_terminal_binding_to_owner_review_signature_registration_and_claim(http):
    h = http
    runner = "00000000-0000-0000-0000-000000000009"
    with Session(h.s["engine"]) as db:
        bound = enrollment.bind(
            db,
            owner="owner-1",
            api_key_id="key-1",
            runner_id=runner,
            origin=ORIGIN,
            key=KEY,
        )
    h.selection = {**h.selection, "enrollment_id": bound["enrollment_id"]}
    h.review = {**h.review, **h.selection}
    review = post(h, "review")
    assert review.status_code == 200 and review.json()["context"]["runner_id"] == runner
    receipt = {**h.selection, "approval": signed(review.json()["context"])}
    assert post(h, "register", receipt).status_code == 200
    response = h.client.post(
        "/jobs/job-1/managed/claim",
        json={**h.body, "runner_id": runner},
        headers=h.headers,
    )
    assert response.status_code == 200
    association = response.json()["managed_authorization"]["authority_snapshot"][
        "enrollment"
    ]
    assert (
        association["id"] == bound["enrollment_id"]
        and association["runner_id"] == runner
    )
    assert state(h)[3:7] == (1, 30, 1, 1)


@pytest.mark.parametrize("operation", ["review", "register", "revoke"])
@pytest.mark.parametrize("scope", ["runner", "full"])
def test_api_keys_never_become_human_approval_provenance(http, operation, scope):
    h = http
    if operation == "revoke":
        register(h)
    with Session(h.s["engine"]) as db:
        db.get(ApiKey, "key-1").scope = scope
        db.commit()
    body = {
        "review": h.review,
        "register": {**h.selection, "approval": h.s["approval"]},
        "revoke": {},
    }[operation]
    before = state(h)
    reply = post(h, operation, body, h.headers)
    assert reply.status_code == 409 and reply.json() == {
        "detail": "managed_approval_refused"
    }
    assert state(h) == before


@pytest.mark.parametrize(
    "kind,status", [("missing", 401), ("invalid", 401), ("foreign", 404)]
)
def test_missing_invalid_or_foreign_owner_session_cannot_review(http, kind, status):
    h = http
    headers = {
        "missing": {},
        "invalid": {"Authorization": "Bearer synthetic_do_not_echo"},
        "foreign": {"Authorization": "Bearer " + mint_token("other")},
    }[kind]
    before = state(h)
    reply = post(h, "review", headers=headers)
    assert reply.status_code == status and state(h) == before
    assert (
        reply.json() == {"detail": "managed_approval_refused"}
        and "synthetic_do_not_echo" not in reply.text
    )


def login(h):
    with Session(h.s["engine"]) as db:
        db.add(
            LocalCredential(
                user_id="owner-1",
                username="operator",
                password_hash=local_auth.PASSWORD_HASHER.hash(PASSWORD),
            )
        )
        db.commit()
    result = h.client.post(
        "/auth/local/login",
        json={"username": "operator", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert result.status_code == 200
    session = h.client.get("/auth/local/session").json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrfToken"]}


def test_local_owner_session_with_csrf_can_review_register_and_revoke(http):
    h = http
    headers = login(h)
    accepted, _ = register(h, headers)
    assert accepted.json()["approval_record_id"] == "managed-fixture:fixture-approval"
    assert post(h, "revoke", {}, headers).status_code == 200
    assert state(h)[7][0][2] is True


@pytest.mark.parametrize(
    "kind,status",
    [
        ("missing_csrf", 403),
        ("bad_csrf", 403),
        ("origin", 403),
        ("revoked", 401),
        ("expired", 401),
        ("disabled", 401),
    ],
)
def test_local_owner_provenance_keeps_csrf_origin_session_and_method_guards(
    http, monkeypatch, kind, status
):
    h = http
    headers = login(h)
    if kind == "missing_csrf":
        headers.pop("X-CSRF-Token")
    elif kind == "bad_csrf":
        headers["X-CSRF-Token"] = "0" * 64
    elif kind == "origin":
        headers["Origin"] = "https://foreign.synthetic.test"
    elif kind == "disabled":
        monkeypatch.setenv("VARDRMAP_AUTH_METHODS", "github")
    else:
        with Session(h.s["engine"]) as db:
            row = db.query(LocalSession).one()
            if kind == "revoked":
                db.delete(row)
            else:
                row.expires_at = local_auth.now() - timedelta(seconds=1)
            db.commit()
    before = state(h)
    reply = post(h, "review", headers=headers)
    assert reply.status_code == status and state(h) == before
    assert reply.json() == {"detail": "managed_approval_refused"}


@pytest.mark.parametrize("change", ["signature", "context", "case", "expired"])
def test_modified_or_stale_human_approval_cannot_be_registered(http, change):
    h = http
    reviewed = post(h, "review").json()
    approval = signed(reviewed["context"])
    if change == "signature":
        approval["signature"] = "A" * 86
    elif change == "context":
        context = {**reviewed["context"], "plan_sha256": "0" * 64}
        approval = signed(context)
    elif change == "case":
        with Session(h.s["engine"]) as db:
            case = copy.deepcopy(db.get(AuthorizationTestCase, "case-1").spec)
            case["request"]["url"] = "https://api.example.test/later"
            db.get(AuthorizationTestCase, "case-1").spec = case
            db.commit()
    else:
        h.s["wall"][0] += timedelta(minutes=2)
    before = state(h)
    reply = post(h, "register", {**h.selection, "approval": approval})
    assert reply.status_code == 409 and state(h) == before


@pytest.mark.parametrize(
    "kind,status",
    [
        ("duplicate", 422),
        ("nonfinite", 422),
        ("utf8", 422),
        ("extra", 422),
        ("key_field", 422),
        ("coerced", 422),
        ("length", 413),
        ("stream", 413),
        ("http", 403),
        ("encoding", 415),
        ("media", 415),
    ],
)
def test_approval_http_is_bounded_strict_and_never_accepts_private_signing_inputs(
    http, kind, status
):
    h = http
    body, path = dict(h.review), PATH + "/review"
    headers = {**h.owner_headers, "Content-Type": "application/json"}
    if kind in {"extra", "key_field", "coerced"}:
        body[
            {"extra": "owner", "key_field": "private_key", "coerced": "max_executions"}[
                kind
            ]
        ] = True if kind == "coerced" else "synthetic_do_not_echo"
    elif kind == "length":
        headers["Content-Length"] = str(boundary.BODY_MAX_BYTES + 1)
    elif kind == "http":
        path = "http://map.synthetic.test" + path
    elif kind == "encoding":
        headers["Content-Encoding"] = "gzip"
    elif kind == "media":
        headers["Content-Type"] = "text/plain"
    data = json.dumps(body).encode()
    if kind == "duplicate":
        data = b'{"private_key":"synthetic_do_not_echo","private_key":1}'
    elif kind == "nonfinite":
        data = b'{"max_executions":1e999}'
    elif kind == "utf8":
        data = b"\xff"
    elif kind == "stream":
        data = iter([b"x" * boundary.BODY_MAX_BYTES, b"x"])
    before = state(h)
    reply = h.client.post(path, content=data, headers=headers)
    assert reply.status_code == status and state(h) == before
    assert reply.json() == {"detail": "managed_approval_refused"}
    assert (
        reply.headers["Cache-Control"] == "no-store"
        and "synthetic_do_not_echo" not in reply.text
    )


@pytest.mark.parametrize(
    "failure,status",
    [("timeout", 408), ("disconnect", 400), ("exception", 503), ("reply_size", 503)],
)
def test_bounded_body_wait_and_service_failures_never_create_approval(
    http, monkeypatch, failure, status
):
    h = http
    if failure == "exception":

        def fail(*args, **kwargs):
            raise RuntimeError("synthetic_do_not_echo")

        monkeypatch.setattr(h.s["service"], "review", fail)
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
            "body": json.dumps(h.review).encode(),
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": PATH + "/review",
            "server": ("map.synthetic.test", 443),
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", h.owner_headers["Authorization"].encode()),
            ],
        },
        receive=receive,
    )
    before = state(h)
    router = boundary.build_approval_router(h.s["service"])
    with Session(h.s["engine"]) as db:
        reply = asyncio.run(router.routes[0].endpoint("job-1", request, db=db))
    assert reply.status_code == status and state(h) == before
    assert "synthetic_do_not_echo" not in reply.body.decode()


def test_human_factory_is_unregistered_and_contains_no_signer_or_key_bootstrap(http):
    from main import app

    paths = {
        route.path for route in boundary.build_approval_router(http.s["service"]).routes
    }
    assert paths == {
        boundary.JOB_PATH + "/approval/" + name
        for name in ("review", "register", "revoke")
    }
    assert paths.isdisjoint(app.openapi()["paths"])


@pytest.mark.parametrize("prefix", ["Bearer  ", "Bearer \t"])
def test_normalized_full_api_key_is_never_human_session_provenance(http, prefix):
    h = http
    with Session(h.s["engine"]) as db:
        db.get(ApiKey, "key-1").scope = "full"
        db.commit()
    before = state(h)
    reply = post(h, "review", headers={"Authorization": prefix + KEY})
    assert reply.status_code == 409 and state(h) == before
    assert reply.json() == {"detail": "managed_approval_refused"}
