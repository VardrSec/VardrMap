"""Opt-in two-repository synthetic ASGI HTTPS; no TLS sockets or Gate execution.

Only the test probe imports Runner. Neither application's product paths import
the other repository. All application-to-application traffic is JSON over the
ASGI HTTP transport; only the disposable database dependency is overridden.
"""

import copy
import hashlib
import importlib.util
import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import execution_control as control
import local_auth
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from db import get_db
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from managed_issuance import Issuer
from managed_wire import WireRefused
from models import (
    ApiKey,
    Authorization,
    Engagement,
    EngagementMember,
    JobExecution,
    LocalCredential,
    LocalSession,
    ManagedApproval,
    ManagedContract,
    ManagedEnrollment,
)
from nm1_authorization import IssuanceRefused
from routers.local_auth import router as local_router
from sqlalchemy.orm import Session
from tests.test_managed_issuance import KEY, NOW, RUNNER, mint_token, signed
from tests.test_managed_issuance import specimen as specimen

pytestmark = pytest.mark.skipif(
    not os.environ.get("NM2_RUNNER_SOURCE"),
    reason="explicit isolated cross-repository harness only",
)
ORIGIN = "https://map.synthetic.test"
PASSWORD = "public synthetic operator password 123!"


@pytest.fixture
def map_origin():
    return ORIGIN


@pytest.fixture
def harness(specimen, tmp_path, monkeypatch, map_origin):
    s = specimen
    source = Path(os.environ["NM2_RUNNER_SOURCE"]).resolve()
    assert (source / "tests" / "managed_http_probe.py").is_file()
    monkeypatch.syspath_prepend(str(source))
    spec = importlib.util.spec_from_file_location(
        "nm2_runner_http_probe", source / "tests" / "managed_http_probe.py"
    )
    probe_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe_module)
    from vardrrunner import launch_guard
    from vardrrunner.authorization.codec import AuthorizationError, TrustAnchor
    from vardrrunner.authorization.ledger import AuthorizationLedger
    from vardrrunner.journal import Journal

    ticks, client_wall = [0.0], [NOW]

    def server_clock():
        return NOW + timedelta(seconds=ticks[0])

    monkeypatch.setattr(control, "now", lambda: server_clock().replace(tzinfo=None))
    monkeypatch.setattr(
        launch_guard,
        "time",
        SimpleNamespace(monotonic=lambda: ticks[0], time=lambda: client_wall[0].timestamp()),
    )
    monkeypatch.setenv("VARDRMAP_AUTH_METHODS", "github,local")
    monkeypatch.setenv("ALLOWED_ORIGINS", map_origin)
    service = Issuer(map_origin, s["wire"], clock=server_clock, monotonic=lambda: ticks[0])
    s["db"].get(ManagedEnrollment, "enrollment-1").origin = map_origin
    s["db"].add(
        LocalCredential(
            user_id="owner-1",
            username="operator",
            password_hash=local_auth.PASSWORD_HASHER.hash(PASSWORD),
        )
    )
    s["db"].commit()

    app = FastAPI()
    app.include_router(local_router)

    def database():
        with Session(s["engine"]) as db:
            yield db

    app.dependency_overrides[get_db] = database

    async def refused(request, exc):
        return JSONResponse({"detail": "synthetic_authorization_refused"}, status_code=409)

    app.add_exception_handler(WireRefused, refused)
    app.add_exception_handler(IssuanceRefused, refused)

    @app.post("/fixture/review")
    def review(body: dict, request: Request, db=Depends(get_db)):
        return service.review(db, request, **body)

    @app.post("/fixture/register")
    def register(body: dict, request: Request, db=Depends(get_db)):
        return {"id": service.register(db, request, **body).id}

    @app.post("/fixture/claim")
    def claim(body: dict, request: Request, db=Depends(get_db)):
        return service.claim(db, request, job_id="job-1", body=control.ClaimControl(**body))

    @app.post("/fixture/current")
    def current(body: dict, request: Request, db=Depends(get_db)):
        args = {k: body.pop(k) for k in ("contract_id", "attempt_id", "fence")}
        return service.refresh(
            db, request, job_id="job-1", body=control.ControlRequest(**body), **args
        )

    @app.post("/fixture/consume")
    def consume(body: dict, request: Request, db=Depends(get_db)):
        args = {k: body.pop(k) for k in ("contract_id", "attempt_id", "fence", "contract_sha256")}
        return service.consume(
            db, request, job_id="job-1", body=control.ControlRequest(**body), **args
        )

    from managed_results import Results

    results = Results(service)
    from managed_stops import Stops

    stops = Stops(results)

    from managed_observations import Observations

    observations = Observations(results)

    @app.post("/fixture/observe")
    def observe(body: dict, request: Request, db=Depends(get_db)):
        args = {k: body.pop(k) for k in ("plan_sha256", "case_sha256", "association_sha256")}
        return observations.inspect(
            db, request, job_id="job-1", body=control.ClaimControl(**body), **args
        )

    def result_args(body):
        return {k: body.pop(k) for k in ("contract_id", "attempt_id", "fence", "contract_sha256")}

    @app.post("/fixture/result")
    def result(body: dict, request: Request, db=Depends(get_db)):
        args = result_args(body)
        artifact, sha = body.pop("artifact"), body.pop("artifact_sha256")
        return results.submit(
            db,
            request,
            job_id="job-1",
            body=control.ControlRequest(**body),
            artifact=artifact,
            artifact_sha256=sha,
            **args,
        )

    @app.post("/fixture/finish")
    def finish(body: dict, request: Request, db=Depends(get_db)):
        args = result_args(body)
        completion = {
            k: body.pop(k) for k in ("receipt_sha256", "outcome", "termination_confirmed")
        }
        return results.finish(
            db, request, job_id="job-1", body=control.ControlRequest(**body), **args, **completion
        )

    @app.post("/fixture/inspect")
    def inspect(body: dict, request: Request, db=Depends(get_db)):
        args = result_args(body)
        return results.inspect(
            db, request, job_id="job-1", body=control.ControlRequest(**body), **args
        )

    @app.post("/fixture/stopped")
    def stopped(body: dict, request: Request, db=Depends(get_db)):
        args = result_args(body)
        report = {k: body.pop(k) for k in ("outcome", "cause", "termination_confirmed")}
        return stops.report(
            db, request, job_id="job-1", body=control.ControlRequest(**body), **args, **report
        )

    @app.post("/fixture/stop-status")
    def stop_status(body: dict, request: Request, db=Depends(get_db)):
        args = result_args(body)
        return stops.inspect(
            db, request, job_id="job-1", body=control.ControlRequest(**body), **args
        )

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
    owner_headers = {"Authorization": "Bearer " + mint_token("owner-1")}
    runner_headers = {"Authorization": "Bearer " + KEY}
    body = s["body"].model_dump(mode="json")
    body["origin"] = map_origin
    review_body = dict(
        job_id="job-1",
        enrollment_id="enrollment-1",
        authorization_id="auth-1",
        plan=s["plan"],
        expires_at="2026-11-02T18:01:00Z",
        max_executions=2,
        max_duration_seconds=60,
        max_artifact_bytes=1000000,
        credential_grants=s["review"]["context"]["credential_grants"],
    )
    vector = json.loads((Path(__file__).parent / "fixtures" / "managed-wire-v1.json").read_text())

    with TestClient(app, base_url=map_origin) as client:

        def issue(headers=None):
            headers = owner_headers if headers is None else headers
            reviewed = client.post("/fixture/review", json=review_body, headers=headers)
            assert reviewed.status_code == 200
            receipt = signed(reviewed.json()["context"])
            registered = client.post(
                "/fixture/register",
                headers=headers,
                json={
                    **{
                        k: review_body[k]
                        for k in ("job_id", "enrollment_id", "authorization_id", "plan")
                    },
                    "approval": receipt,
                },
            )
            assert registered.status_code == 200
            return receipt

        class Transport:
            def post(self, path, *, json):
                return client.post(path, json=json, headers=runner_headers)

        def probe(transport=None, path=None):
            ledger = AuthorizationLedger(
                Journal(path or tmp_path / "runner-journal.db"),
                clock=lambda: max(client_wall[0], server_clock()),
                monotonic=lambda: ticks[0],
            )
            return probe_module.Probe(
                transport or Transport(),
                anchors,
                ledger,
                origin=map_origin,
                runner_id=RUNNER,
                job_id="job-1",
                engagement_id="eng-1",
                principal_sha256=hashlib.sha256(("Bearer " + KEY).encode()).hexdigest(),
                case=copy.deepcopy(vector["case"]),
                execution=copy.deepcopy(vector["execution"]),
                tool_sha256=s["plan"]["tool_sha256"],
                clock=lambda: client_wall[0],
                monotonic=lambda: ticks[0],
            )

        def login():
            assert (
                client.post(
                    "/auth/local/login",
                    json={"username": "operator", "password": PASSWORD},
                    headers={"Origin": map_origin},
                ).status_code
                == 200
            )
            result = client.get("/auth/local/session")
            assert result.status_code == 200
            return {"Origin": map_origin, "X-CSRF-Token": result.json()["csrfToken"]}

        yield SimpleNamespace(
            s=s,
            app=app,
            client=client,
            issue=issue,
            probe=probe,
            login=login,
            body=body,
            review=review_body,
            owner=owner_headers,
            runner=runner_headers,
            ticks=ticks,
            wall=client_wall,
            transport=Transport,
            error=AuthorizationError,
            service=service,
            origin=map_origin,
        )


@pytest.mark.parametrize("auth", ["jwt", "local"])
def test_http_to_shared_validator_ledger_and_inert_launch(harness, auth):
    h = harness
    h.issue(h.login() if auth == "local" else h.owner)
    p = h.probe()
    p.claim(h.body)
    p.reserve()
    launched = []
    p.launch(lambda: launched.append(True))
    assert launched == [True]
    with pytest.raises(h.error, match="single_launch_only"):
        p.launch(lambda: launched.append(True))
    h.s["db"].expire_all()
    assert h.s["db"].query(ManagedContract).one().consumed is False
    assert h.s["db"].query(ManagedApproval).one().issued == 1
    assert h.s["db"].get(Engagement, "eng-1").duration_allocated == 30


@pytest.mark.parametrize(
    "kind",
    ["missing", "expired", "foreign", "viewer", "api_runner", "api_full", "disabled"],
)
def test_http_review_requires_actual_owner_session(harness, monkeypatch, kind):
    h = harness
    headers = dict(h.owner)
    if kind == "missing":
        headers = {}
    elif kind == "expired":
        import jwt

        headers["Authorization"] = "Bearer " + jwt.encode(
            {
                "sub": "owner-1",
                "aud": "vardrmap-backend",
                "iss": "vardrmap-frontend",
                "exp": 1,
            },
            "test-secret-key-for-pytest-needs-32-chars!!",
            algorithm="HS256",
        )
    elif kind in {"foreign", "viewer"}:
        headers["Authorization"] = "Bearer " + mint_token("foreign-owner")
        if kind == "viewer":
            h.s["db"].add(
                EngagementMember(
                    program_id="eng-1",
                    owner_github_id="owner-1",
                    member_github_id="foreign-owner",
                    role="viewer",
                )
            )
            h.s["db"].commit()
    elif kind.startswith("api"):
        headers = h.runner
        if kind == "api_full":
            h.s["db"].get(ApiKey, "key-1").scope = "full"
            h.s["db"].commit()
    elif kind == "disabled":
        monkeypatch.setenv("VARDRMAP_AUTH_METHODS", "local")
    response = h.client.post("/fixture/review", headers=headers, json=h.review)
    assert response.status_code in {401, 404, 409}
    assert h.s["db"].query(ManagedApproval).count() == 0


@pytest.mark.parametrize(
    "kind",
    ["missing_csrf", "bad_csrf", "origin", "http", "revoked", "expired", "disabled"],
)
def test_http_local_provenance_and_csrf_fail_closed(harness, monkeypatch, kind):
    h = harness
    headers = h.login()
    if kind == "missing_csrf":
        headers.pop("X-CSRF-Token")
    elif kind == "bad_csrf":
        headers["X-CSRF-Token"] = "0" * 64
    elif kind == "origin":
        headers["Origin"] = "https://foreign.synthetic.test"
    elif kind in {"expired", "revoked"}:
        session = h.s["db"].query(LocalSession).one()
        if kind == "expired":
            session.expires_at = local_auth.now() - timedelta(seconds=1)
        else:
            h.s["db"].delete(session)
        h.s["db"].commit()
    elif kind == "disabled":
        monkeypatch.setenv("VARDRMAP_AUTH_METHODS", "github")
    if kind == "http":
        # Force the cookie onto HTTP to test the server's transport check too.
        headers["Cookie"] = (
            local_auth.COOKIE_NAME + "=" + h.client.cookies.get(local_auth.COOKIE_NAME)
        )
    response = h.client.post(
        ("http://map.synthetic.test" if kind == "http" else "") + "/fixture/review",
        headers=headers,
        json=h.review,
    )
    assert response.status_code in {400, 401, 403}


@pytest.mark.parametrize(
    "kind", ["approval", "enrollment", "key", "cancel", "authority", "lease", "expiry"]
)
def test_current_denials_never_renew_or_reach_launch(harness, kind):
    h = harness
    h.issue()
    p = h.probe()
    p.claim(h.body)
    p.reserve()
    with Session(h.s["engine"]) as db:
        before = db.get(JobExecution, "job-1").expires_at
        if kind == "approval":
            db.query(ManagedApproval).one().revoked = True
        elif kind == "enrollment":
            db.get(ManagedEnrollment, "enrollment-1").revoked = True
        elif kind == "key":
            db.delete(db.get(ApiKey, "key-1"))
        elif kind == "cancel":
            db.get(JobExecution, "job-1").state = "cancel_requested"
        elif kind == "authority":
            db.get(Engagement, "eng-1").managed_authority_revision += 1
        elif kind == "lease":
            h.ticks[0] = 11
        elif kind == "expiry":
            h.ticks[0] = 61
        db.commit()
    denied = h.client.post("/fixture/current", json=p.request, headers=h.runner)
    assert denied.status_code in {401, 404, 409}
    with pytest.raises(h.error):
        p.launch(lambda: pytest.fail("inert sentinel reached after denial"))
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == before
        assert db.get(JobExecution, "job-1").capacity_reserved


@pytest.mark.parametrize(
    "field",
    [
        "origin",
        "runner_id",
        "job_id",
        "contract_id",
        "attempt_id",
        "fence",
        "authority_revision",
        "authority_sha256",
        "action",
        "lease_seconds",
        "lease_expires_at",
    ],
)
def test_current_response_binding_is_verified_before_status(harness, field):
    h = harness
    h.issue()

    class Tamper(h.transport):
        def post(self, path, *, json):
            reply = super().post(path, json=json)
            if path.endswith("current"):
                payload = reply.json()
                payload[field] = (
                    2
                    if field in {"fence", "authority_revision"}
                    else 11
                    if field == "lease_seconds"
                    else "changed"
                )
                return SimpleNamespace(status_code=200, json=lambda: payload)
            return reply

    p = h.probe(Tamper())
    p.claim(h.body)
    with pytest.raises(h.error):
        p.reserve()
    assert not p.context.managed_status_verified


@pytest.mark.parametrize("kind", ["timeout", "malformed", "late", "cancel"])
def test_transport_denial_prevents_permission(harness, kind):
    h = harness
    h.issue()

    class Fault(h.transport):
        def post(self, path, *, json):
            reply = super().post(path, json=json)
            if path.endswith("current"):
                if kind == "timeout":
                    raise TimeoutError("public synthetic transport fault")
                if kind == "late":
                    h.ticks[0] += 11
                if kind == "malformed":
                    return SimpleNamespace(status_code=200, json=lambda: [])
                if kind == "cancel":
                    payload = reply.json()
                    payload["action"] = "cancel"
                    return SimpleNamespace(status_code=200, json=lambda: payload)
            return reply

    p = h.probe(Fault())
    p.claim(h.body)
    with pytest.raises(h.error):
        p.reserve()


def test_lost_claim_response_is_reserved_without_automatic_retry(harness):
    h = harness
    h.issue()

    class Lost(h.transport):
        def post(self, path, *, json):
            super().post(path, json=json)
            raise TimeoutError("public synthetic dropped claim response")

    p = h.probe(Lost())
    with pytest.raises(h.error):
        p.claim(h.body)
    with pytest.raises(h.error, match="single_claim_only"):
        p.claim(h.body)
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedContract).count() == 1
        assert db.query(ManagedApproval).one().issued == 1
        assert db.get(JobExecution, "job-1").capacity_reserved


def test_durable_ledger_denies_same_contract_after_restart(harness):
    h = harness
    h.issue()
    first = h.probe()
    claimed = first.claim(h.body)
    first.reserve()

    class Replay(h.transport):
        def post(self, path, *, json):
            if path.endswith("claim"):
                return SimpleNamespace(status_code=200, json=lambda: copy.deepcopy(claimed))
            return super().post(path, json=json)

    restarted = h.probe(Replay())
    restarted.claim(h.body)
    with pytest.raises(h.error, match="contract_replayed_or_changed"):
        restarted.reserve()


@pytest.mark.parametrize("kind", ["allocation", "grant", "approval", "testing", "rollback"])
def test_strictest_deadline_prevents_final_launch(harness, kind):
    h = harness
    if kind == "grant":
        h.review["credential_grants"][0]["expires_at"] = "2026-11-02T18:00:03Z"
    elif kind == "approval":
        h.review["expires_at"] = "2026-11-02T18:00:03Z"
    elif kind == "testing":
        h.s["db"].get(Authorization, "auth-1").window_end = NOW + timedelta(seconds=3)
        h.s["db"].commit()
        h.review["expires_at"] = "2026-11-02T18:00:03Z"
    h.issue()
    if kind == "allocation":
        h.body["duration_seconds"] = 3
    p = h.probe()
    p.claim(h.body)
    p.reserve()
    h.ticks[0] = 4 if kind != "rollback" else 31
    if kind == "rollback":
        h.wall[0] = NOW - timedelta(hours=1)
    with pytest.raises((h.error, RuntimeError)):
        p.launch(lambda: pytest.fail("expired sentinel reached"))


def test_no_test_routes_registered_in_production_app(harness):
    from main import app

    assert not any(path.startswith("/fixture/") for path in app.openapi()["paths"])


def test_renewal_never_extends_original_allocation(harness):
    h = harness
    h.issue()
    p = h.probe()
    p.claim(h.body)
    p.reserve()
    for tick, expected_end in [(8, 18), (16, 26), (24, 30), (29, 30)]:
        h.ticks[0] = tick
        p.revalidate()
        with Session(h.s["engine"]) as db:
            assert db.get(JobExecution, "job-1").expires_at == (
                NOW + timedelta(seconds=expected_end)
            ).replace(tzinfo=None)
            assert db.get(Engagement, "eng-1").duration_allocated == 30
    h.ticks[0] = 30
    response = h.client.post("/fixture/current", json=p.request, headers=h.runner)
    assert response.status_code == 409


@pytest.mark.parametrize(
    "field", ["origin", "runner_id", "token", "contract_id", "attempt_id", "fence"]
)
def test_current_request_mismatch_does_not_renew(harness, field):
    h = harness
    h.issue()
    p = h.probe()
    p.claim(h.body)
    p.reserve()
    request = copy.deepcopy(p.request)
    request[field] = (
        2
        if field == "fence"
        else "https://foreign.synthetic.test"
        if field == "origin"
        else "00000000-0000-0000-0000-000000000099"
        if field == "runner_id"
        else "x" * 40
    )
    h.ticks[0] = 2
    response = h.client.post("/fixture/current", json=request, headers=h.runner)
    assert response.status_code in {404, 409}
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == (NOW + timedelta(seconds=10)).replace(
            tzinfo=None
        )


@pytest.mark.parametrize("phase", ["setup", "preflight", "verification", "reset"])
def test_shared_compiler_binds_all_auxiliary_requests(harness, phase):
    h = harness
    h.issue()
    p = h.probe()
    p.claim(h.body)
    if phase == "setup":
        request = p.case["setup"][0]["request"]
    elif phase == "preflight":
        request = p.case["identities"][0]["preflight"]
    elif phase == "verification":
        request = p.case["write_verification"]["request"]
    else:
        request = p.case["write_verification"]["reset"]["request"]
    request["url"] += "/unapproved-change"
    with pytest.raises(h.error, match="execution_plan_changed"):
        p.reserve()


def test_launch_wait_and_resolution_latency_consume_permission(harness):
    h = harness
    h.issue()
    p = h.probe()
    p.claim(h.body)
    p.reserve()
    from contextlib import contextmanager
    from vardrrunner import launch_guard

    @contextmanager
    def delayed_creation_boundary():
        h.ticks[0] = 31
        yield

    with launch_guard.install(delayed_creation_boundary), pytest.raises(h.error):
        p.launch(lambda: pytest.fail("sentinel reached after waiting at launch boundary"))


def test_claim_latency_counts_against_initial_lease(harness):
    h = harness
    h.issue()

    class SlowClaim(h.transport):
        def post(self, path, *, json):
            response = super().post(path, json=json)
            if path.endswith("claim"):
                h.ticks[0] = 11
            return response

    p = h.probe(SlowClaim())
    p.claim(h.body)
    with pytest.raises(h.error, match="permission_expired"):
        p.reserve()


def test_post_flush_expiry_rolls_back_renewal(harness, monkeypatch):
    h = harness
    h.issue()
    p = h.probe()
    p.claim(h.body)
    p.reserve()
    h.ticks[0] = 2
    original = h.service._locked_time
    calls = []

    def delayed(db, now):
        calls.append(True)
        if len(calls) == 2:
            h.ticks[0] = 61
        return original(db, now)

    monkeypatch.setattr(h.service, "_locked_time", delayed)
    assert h.client.post("/fixture/current", json=p.request, headers=h.runner).status_code == 409
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == (NOW + timedelta(seconds=10)).replace(
            tzinfo=None
        )
        assert db.query(ManagedApproval).one().issued == 1
        assert db.get(Engagement, "eng-1").duration_allocated == 30


def test_tool_deadline_survives_renewal_and_client_clock_rollback(harness):
    h = harness
    h.issue()
    h.body["duration_seconds"] = 60
    p = h.probe()
    p.claim(h.body)
    p.reserve()
    for tick in (8, 16, 24):
        h.ticks[0] = tick
        p.revalidate()
    # The Map allocation and live lease still permit execution at second 31;
    # the compiled tool's original 30-second ceiling must independently refuse.
    assert p.lease_end == 34
    h.ticks[0] = 31
    h.wall[0] = NOW - timedelta(hours=1)
    with pytest.raises(h.error, match="permission_expired"):
        p.launch(lambda: pytest.fail("tool deadline extended by renewal or rollback"))


@pytest.mark.parametrize("change", ["scope", "approval_id", "purpose"])
def test_altered_receipt_cannot_replace_operator_approval(harness, change):
    h = harness
    reviewed = h.client.post("/fixture/review", headers=h.owner, json=h.review)
    assert reviewed.status_code == 200
    receipt = signed(reviewed.json()["context"])
    from managed_wire import b64, canonical, parse, unb64

    payload = parse(unb64(receipt["payload"], 256 * 1024))
    if change == "scope":
        payload["context"]["scope"] = []
    elif change == "approval_id":
        payload["approval_id"] = "ai-self-approved"
    else:
        receipt["purpose"] = "contract"
    receipt["payload"] = b64(canonical(payload))
    result = h.client.post(
        "/fixture/register",
        headers=h.owner,
        json={
            **{k: h.review[k] for k in ("job_id", "enrollment_id", "authorization_id", "plan")},
            "approval": receipt,
        },
    )
    assert result.status_code == 409
    assert h.s["db"].query(ManagedApproval).count() == 0


@pytest.mark.parametrize("rollback", [False, True])
def test_cached_current_reply_cannot_extend_actual_server_lease(harness, rollback):
    h = harness
    h.issue()

    class Cached(h.transport):
        captured = None

        def post(self, path, *, json):
            if path.endswith("current"):
                if self.captured is None:
                    self.captured = copy.deepcopy(super().post(path, json=json).json())
                return SimpleNamespace(status_code=200, json=lambda: copy.deepcopy(self.captured))
            return super().post(path, json=json)

    p = h.probe(Cached())
    p.claim(h.body)
    p.reserve()  # The only real server renewal ends at t10.
    h.ticks[0] = 8
    if rollback:
        h.wall[0] = NOW - timedelta(hours=1)
    p.revalidate()  # Captured JSON must not create a later lease.
    assert p.lease_end <= 10
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == (NOW + timedelta(seconds=10)).replace(
            tzinfo=None
        )
    h.ticks[0] = 11
    with pytest.raises(h.error, match="permission_expired"):
        p.launch(lambda: pytest.fail("cached control reply revived expired server lease"))


@pytest.mark.parametrize("lost", [False, True])
def test_http_consumption_receipt_to_runner_barrier(harness, lost):
    """Real API-key auth and JSON ACK, production Runner parser, inert endpoint."""
    from vardrrunner.authorization.claim import ClaimError, ManagedRun
    from vardrrunner.authorization.codec import digest, encoded

    h = harness
    h.issue()
    probe = h.probe()
    probe.claim(h.body)
    probe.reserve()
    binding = {
        **probe.binding,
        **{k: probe.payload[k] for k in ("contract_id", "attempt_id", "fence")},
        "authority_revision": probe.context.authority_revision,
        "authority_sha256": probe.context.authority_sha256,
    }
    states, sends = [], []

    def record(run_id, owner, *, acknowledged):
        states.append(acknowledged)

    def consume(body):
        sends.append(True)
        result = probe.post("/fixture/consume", body)
        if lost:
            raise OSError("synthetic lost reply after actual server commit")
        return result

    handle = ManagedRun(
        SimpleNamespace(binding=binding, envelope=probe.envelope),
        SimpleNamespace(consumption=record),
        "inert-run",
        "inert-owner",
        1000000,
        consume,
    )
    body = {**probe.request, "contract_sha256": digest(encoded(probe.envelope))}
    if lost:
        with pytest.raises(ClaimError, match="consumption_outcome_unknown"):
            handle._acknowledge(body)
    else:
        handle._acknowledge(body)
    assert states == ([False] if lost else [False, True]) and len(sends) == 1
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedContract).one().consumed
        assert db.get(JobExecution, "job-1").capacity_reserved
        assert db.query(ManagedApproval).one().issued == 1
    # A second invocation cannot turn the retained server tombstone into a new ACK.
    assert h.client.post("/fixture/consume", json=body, headers=h.runner).status_code == 409


def test_http_managed_evidence_completion_receipts(harness):
    from tests.managed_result_probe import flow

    harness.issue()
    flow(harness)


def test_http_owned_managed_stop_receipt(harness):
    from tests.managed_stop_probe import flow

    harness.issue()
    flow(harness)


@pytest.mark.parametrize("kind", ["result", "stop"])
def test_http_capability_free_claim_observation(harness, kind):
    from tests.managed_observation_probe import flow

    harness.issue()
    flow(harness, kind=kind)
