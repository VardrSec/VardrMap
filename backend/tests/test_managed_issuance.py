"""Unregistered transactional issuer; disposable state and public test keys only."""

import copy
import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import execution_control as control
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from db import Base
from fastapi import HTTPException
from managed_issuance import Issuer
from managed_wire import ContractWire, OperatorAnchor, WireRefused, b64, canonical, message, stamp
from models import (
    ApiKey,
    Authorization,
    AuthorizationTestCase,
    Engagement,
    JobExecution,
    ManagedApproval,
    ManagedClock,
    ManagedContract,
    ManagedEnrollment,
    ScanJob,
    ScopeItem,
    User,
)
from nm1_authorization import IssuanceRefused
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.requests import Request

NOW = datetime(2026, 11, 2, 18, tzinfo=timezone.utc)
ORIGIN = "http://127.0.0.1:51991"
KEY = "vmap_public_disposable_managed_issuance_fixture"
SEED = bytes(range(32))
RUNNER = str(uuid.UUID(int=7))


def request(bearer):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/fixture",
            "headers": [(b"authorization", ("Bearer " + bearer).encode())],
        }
    )


def mint_token(owner):
    return jwt.encode(
        {
            "sub": owner,
            "aud": "vardrmap-backend",
            "iss": "vardrmap-frontend",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "test-secret-key-for-pytest-needs-32-chars!!",
        algorithm="HS256",
    )


def signed(context, approval_id="fixture-approval"):
    payload = {
        "schema": "vardr.execution-approval/1",
        "issuer": {"id": "managed-fixture", "key_id": "operator-1"},
        "origin": "map",
        "approval_id": approval_id,
        "approver_id": "owner-1",
        "approved_at": stamp(NOW),
        "context": context,
    }
    data = canonical(payload)
    return {
        "format": "vardr.authorization-envelope/1",
        "purpose": "approval",
        "payload": b64(data),
        "signature": b64(
            Ed25519PrivateKey.from_private_bytes(SEED).sign(message("approval", data))
        ),
    }


@pytest.fixture
def specimen(tmp_path):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "fixture.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    vector = json.loads((Path(__file__).parent / "fixtures" / "managed-wire-v1.json").read_text())
    wall = [NOW]
    ticks = [0.0]
    wire = ContractWire(
        "managed-fixture",
        "contract-1",
        bytes(range(32, 64)),
        (
            OperatorAnchor(
                "managed-fixture",
                "operator-1",
                "owner-1",
                Ed25519PrivateKey.from_private_bytes(SEED).public_key().public_bytes_raw(),
            ),
        ),
    )
    service = Issuer(ORIGIN, wire, clock=lambda: wall[0], monotonic=lambda: ticks[0])
    owner_request = request(mint_token("owner-1"))
    runner_request = request(KEY)
    with Session(engine) as db:
        db.add(User(github_id="owner-1", username="fixture"))
        db.commit()
        db.add_all(
            [
                ApiKey(
                    id="key-1",
                    github_id="owner-1",
                    key_hash=hashlib.sha256(KEY.encode()).hexdigest(),
                    scope="runner",
                ),
                Engagement(
                    id="eng-1",
                    owner_github_id="owner-1",
                    name="Fixture",
                    engagement_type="pentest",
                    engagement_status="active",
                    concurrency_limit=1,
                    target_limit=10,
                    targets_spent=0,
                    duration_limit=120,
                    duration_allocated=0,
                ),
            ]
        )
        db.commit()
        db.add_all(
            [
                Authorization(
                    id="auth-1",
                    program_id="eng-1",
                    owner_github_id="owner-1",
                    permits="Synthetic only",
                    status="active",
                    window_start=NOW - timedelta(hours=1),
                    window_end=NOW + timedelta(hours=1),
                ),
                AuthorizationTestCase(
                    id="case-1",
                    program_id="eng-1",
                    owner_github_id="owner-1",
                    name="Fixture",
                    spec=vector["case"],
                ),
                ScopeItem(
                    program_id="eng-1",
                    value="https://api.example.test",
                    kind="url",
                    scope_type="in",
                ),
                ScanJob(
                    id="job-1",
                    program_id="eng-1",
                    owner_github_id="owner-1",
                    tool_type="vardrgate_api_test",
                    target_source="scope",
                    authorization_contract_required=True,
                    config={"test_case_id": "case-1"},
                    status="pending",
                ),
                ManagedEnrollment(
                    id="enrollment-1",
                    api_key_id="key-1",
                    owner="owner-1",
                    principal_hash=hashlib.sha256(("Bearer " + KEY).encode()).hexdigest(),
                    runner_id=RUNNER,
                    origin=ORIGIN,
                    revision=1,
                    revoked=False,
                ),
            ]
        )
        db.commit()
        review = service.review(
            db,
            owner_request,
            job_id="job-1",
            enrollment_id="enrollment-1",
            authorization_id="auth-1",
            plan=vector["plan"],
            expires_at=stamp(NOW + timedelta(minutes=1)),
            max_executions=2,
            max_duration_seconds=60,
            max_artifact_bytes=1000000,
            credential_grants=vector["context"]["credential_grants"],
        )
        approval = signed(review["context"])
        body = control.ClaimControl(
            runner_id=RUNNER,
            origin=ORIGIN,
            concurrency_budget=True,
            duration_seconds=30,
            target_binding={
                "profile": "gate-fixed-http/1",
                "case_sha256": vector["plan"]["case_hash"],
                "origins": ["https://api.example.test:443"],
            },
        )
        yield {
            "db": db,
            "engine": engine,
            "service": service,
            "wire": wire,
            "wall": wall,
            "ticks": ticks,
            "owner": owner_request,
            "runner": runner_request,
            "review": review,
            "plan": vector["plan"],
            "approval": approval,
            "body": body,
        }
    engine.dispose()


def register(s, approval=None):
    return s["service"].register(
        s["db"],
        s["owner"],
        job_id="job-1",
        enrollment_id="enrollment-1",
        authorization_id="auth-1",
        plan=s["plan"],
        approval=approval or s["approval"],
    )


def claim(s, db=None, body=None, req=None):
    return s["service"].claim(
        db or s["db"], req or s["runner"], job_id="job-1", body=body or s["body"]
    )


def unchanged(s, issued=0):
    db = s["db"]
    db.rollback()
    job, eng = db.get(ScanJob, "job-1"), db.get(Engagement, "eng-1")
    assert job.status == "pending" and job.case_snapshot is None
    assert eng.targets_spent == 0 and eng.duration_allocated == 0
    assert db.query(JobExecution).count() == db.query(ManagedContract).count() == 0
    row = db.query(ManagedApproval).first()
    assert row is None or row.issued == issued


def test_exact_owner_review_registration_claim_and_replay(specimen):
    s = specimen
    row = register(s)
    assert row.issued == 0 and not row.revoked
    assert register(s).id == row.id  # Exact registration retry cannot reset counters.
    result = claim(s)
    assert (
        result["managed_authorization"]["authority_snapshot"] == s["review"]["authority_snapshot"]
    )
    db = s["db"]
    contract = db.query(ManagedContract).one()
    assert (contract.ordinal, contract.fence, contract.consumed) == (1, 1, False)
    assert db.query(ManagedApproval).one().issued == 1
    assert db.get(JobExecution, "job-1").capacity_reserved
    assert db.get(Engagement, "eng-1").targets_spent == 1
    assert db.get(Engagement, "eng-1").duration_allocated == 30
    with pytest.raises(WireRefused, match="pending_job_required"):
        claim(s)
    assert db.query(ManagedApproval).one().issued == 1
    assert db.get(Engagement, "eng-1").duration_allocated == 30


@pytest.mark.parametrize(
    "change",
    [
        "runner",
        "origin",
        "principal",
        "enrollment_revoked",
        "key_revoked",
        "approval_revoked",
        "authority_revoked",
        "scope",
        "case",
        "stop",
        "expired",
        "exhausted",
        "duration",
        "missing_controls",
    ],
)
def test_denials_rollback_ownership_ordinal_fence_and_all_budgets(specimen, change):
    s = specimen
    row = register(s)
    db = s["db"]
    body, req = s["body"], s["runner"]
    spent = 0
    if change == "runner":
        body = body.model_copy(update={"runner_id": uuid.UUID(int=8)})
    elif change == "origin":
        body = body.model_copy(update={"origin": "https://other.example.test"})
    elif change == "principal":
        req = request("vmap_unenrolled_public_fixture")
    elif change == "enrollment_revoked":
        db.get(ManagedEnrollment, "enrollment-1").revoked = True
    elif change == "key_revoked":
        db.delete(db.get(ApiKey, "key-1"))
    elif change == "approval_revoked":
        s["service"].revoke(db, s["owner"], job_id="job-1")
    elif change == "authority_revoked":
        db.get(Authorization, "auth-1").status = "revoked"
    elif change == "scope":
        db.query(ScopeItem).one().scope_type = "out"
    elif change == "case":
        db.get(AuthorizationTestCase, "case-1").spec = {"changed": True}
    elif change == "stop":
        db.get(Engagement, "eng-1").stop_work_at = NOW
    elif change == "expired":
        s["wall"][0] = NOW + timedelta(minutes=2)
    elif change == "exhausted":
        row.issued = spent = 2
    elif change == "duration":
        body = body.model_copy(update={"duration_seconds": 61})
    else:
        body = body.model_copy(update={"concurrency_budget": False})
    db.commit()
    with pytest.raises((WireRefused, IssuanceRefused, HTTPException)):
        claim(s, body=body, req=req)
    unchanged(s, issued=spent)


@pytest.mark.parametrize("scope", ["runner", "full"])
def test_api_credentials_cannot_register_even_valid_human_receipt(specimen, scope):
    s = specimen
    s["db"].get(ApiKey, "key-1").scope = scope
    s["db"].commit()
    with pytest.raises(WireRefused, match="operator_session_required"):
        s["service"].register(
            s["db"],
            s["runner"],
            job_id="job-1",
            enrollment_id="enrollment-1",
            authorization_id="auth-1",
            plan=s["plan"],
            approval=s["approval"],
        )
    unchanged(s)
    assert s["db"].get(ScanJob, "job-1").managed_approval_id is None


@pytest.mark.parametrize(
    "field",
    ["job_id", "engagement_id", "runner_id", "authority_sha256", "plan_sha256", "max_executions"],
)
def test_signed_changed_context_cannot_register(specimen, field):
    s = specimen
    context = copy.deepcopy(s["review"]["context"])
    context[field] = 3 if field == "max_executions" else "different"
    # Changing limits is a legitimate new human approval if the trusted projection
    # was actually reviewed. Identity/hash drift must still be refused.
    if field == "max_executions":
        context[field] = 0
    with pytest.raises((WireRefused, IssuanceRefused)):
        register(s, signed(context))
    unchanged(s)


def test_expiry_during_signing_rolls_back_and_denial_clock_survives(specimen):
    s = specimen
    register(s)
    original = s["wire"].issue

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        s["wall"][0] = NOW + timedelta(minutes=2)
        s["ticks"][0] = 120.0
        return result

    with patch.object(s["wire"], "issue", delayed):
        with pytest.raises(WireRefused, match="expired_or_not_yet_valid"):
            claim(s)
    unchanged(s)
    assert s["db"].get(ManagedClock, 1).observed >= (NOW + timedelta(minutes=2)).replace(
        tzinfo=None
    )
    s["wall"][0], s["ticks"][0] = NOW, 0.0
    with pytest.raises(WireRefused, match="clock_rollback"):
        claim(s)
    unchanged(s)


def test_concurrent_claims_have_one_global_winner(specimen):
    s = specimen
    register(s)
    s["db"].rollback()
    barrier = threading.Barrier(4)

    def attempt(_):
        with Session(s["engine"]) as db:
            barrier.wait(timeout=5)
            try:
                claim(s, db=db)
                return True
            except (WireRefused, HTTPException):
                return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(4))) == 1
    s["db"].expire_all()
    assert s["db"].query(ManagedContract).count() == 1
    assert s["db"].query(ManagedApproval).one().issued == 1
    assert s["db"].get(Engagement, "eng-1").duration_allocated == 30


@pytest.mark.parametrize("operation", ["register", "claim"])
def test_interleaved_denial_high_water_cannot_be_overwritten(specimen, operation):
    s = specimen
    if operation == "claim":
        register(s)
    other = Issuer(ORIGIN, s["wire"], clock=lambda: NOW + timedelta(minutes=2), monotonic=lambda: 0)
    sqlite = s["engine"].dialect.name == "sqlite"
    method = (
        "_begin_write"
        if sqlite
        else "_review_locked"
        if operation == "register"
        else "_claim_permission"
    )
    original = getattr(s["service"], method)

    def interleaved(*args, **kwargs):
        result = None if sqlite else original(*args, **kwargs)
        # Independent B observes a later trusted time and denies the same receipt
        # as expired. Its durable observation commits before A reserves anything.
        with Session(s["engine"]) as db:
            with pytest.raises(WireRefused, match="expired_or_not_yet_valid"):
                with other.operation(db) as now:
                    other.wire.approval(s["approval"], s["review"]["context"], "owner-1", now())
        return original(*args, **kwargs) if sqlite else result

    with patch.object(s["service"], method, interleaved):
        with pytest.raises(WireRefused, match="clock_rollback"):
            register(s) if operation == "register" else claim(s)
    unchanged(s)
    assert s["db"].get(ManagedClock, 1).observed >= (NOW + timedelta(minutes=2)).replace(
        tzinfo=None
    )
    if operation == "register":
        assert s["db"].get(ScanJob, "job-1").managed_approval_id is None


@pytest.mark.parametrize("mutation", ["authorization", "scope"])
def test_real_mutation_paths_change_and_revert_cannot_revive_approval(specimen, mutation):
    s = specimen
    register(s)
    user = {"github_id": "owner-1", "scope": "full"}
    if mutation == "authorization":
        from routers.authorizations import update_authorization
        from schemas import AuthorizationUpdate

        for status in ("revoked", "active"):
            update_authorization(
                "eng-1", "auth-1", AuthorizationUpdate(status=status), user, s["db"]
            )
    else:
        from routers.scope import add_out_scope_item, delete_scope_item
        from schemas import ScopeItemCreate

        result = add_out_scope_item(
            "eng-1", ScopeItemCreate(value="https://api.example.test", kind="url"), user, s["db"]
        )
        delete_scope_item("eng-1", "out", result["id"], user, s["db"])
    assert s["db"].get(Engagement, "eng-1").managed_authority_revision == 2
    with pytest.raises(WireRefused, match="authority_revision_changed"):
        claim(s)
    unchanged(s)


def test_missing_approval_and_legacy_claims_fail_closed(specimen):
    s = specimen
    with pytest.raises(WireRefused, match="approval_unavailable"):
        claim(s)
    unchanged(s)

    from routers.jobs import claim_job, serialize_job

    assert serialize_job(s["db"].get(ScanJob, "job-1"))["authorization_contract_required"] is True
    for body in (None, s["body"]):
        with pytest.raises(HTTPException) as denied:
            claim_job(
                "job-1", s["runner"], body, {"github_id": "owner-1", "scope": "runner"}, s["db"]
            )
        assert denied.value.status_code == 409
        unchanged(s)
    register(s)
    with pytest.raises(HTTPException) as denied:
        claim_job("job-1", s["runner"], None, {"github_id": "owner-1", "scope": "runner"}, s["db"])
    assert denied.value.status_code == 409
    unchanged(s)


def test_explicit_queue_requirement_is_inert_before_any_approval(specimen):
    s = specimen
    from routers.jobs import JobCreate, claim_job, create_job

    user = {"github_id": "owner-1", "scope": "full"}
    created = create_job(
        "eng-1",
        JobCreate(
            tool_type="vardrgate_api_test",
            target_source="scope",
            config={"test_case_id": "case-1"},
            authorization_contract_required=True,
        ),
        user,
        s["db"],
    )
    assert created["authorization_contract_required"] is True
    assert s["db"].get(ScanJob, created["id"]).managed_approval_id is None
    with pytest.raises(HTTPException) as denied:
        claim_job(created["id"], s["runner"], None, user, s["db"])
    assert denied.value.status_code == 409
    assert s["db"].query(ManagedApproval).count() == s["db"].query(JobExecution).count() == 0
    assert s["db"].get(ScanJob, created["id"]).status == "pending"


@pytest.mark.parametrize("at_stage", [False, True])
def test_pipeline_cannot_silently_drop_contract_requirement(specimen, at_stage):
    s = specimen
    from routers.jobs import PipelineCreate, PipelineStage, create_pipeline

    body = PipelineCreate(
        stages=[
            PipelineStage(
                tool_type="httpx", target_source="scope", authorization_contract_required=at_stage
            )
        ],
        authorization_contract_required=not at_stage,
    )
    with pytest.raises(HTTPException) as denied:
        create_pipeline("eng-1", body, {"github_id": "owner-1", "scope": "full"}, s["db"])
    assert denied.value.status_code == 400
    assert s["db"].query(ScanJob).count() == 1


def test_cross_engagement_operator_has_no_approval_access(specimen):
    s = specimen
    s["db"].add(User(github_id="other-owner", username="fixture-other"))
    s["db"].commit()
    with pytest.raises(HTTPException) as denied:
        s["service"].register(
            s["db"],
            request(mint_token("other-owner")),
            job_id="job-1",
            enrollment_id="enrollment-1",
            authorization_id="auth-1",
            plan=s["plan"],
            approval=s["approval"],
        )
    assert denied.value.status_code == 404
    unchanged(s)


def test_current_contract_binding_observes_revision_and_legacy_control_stays_disabled(specimen):
    s = specimen
    register(s)
    issued = claim(s)
    row = s["db"].query(ManagedContract).one()
    body = control.ControlRequest(
        runner_id=RUNNER, origin=ORIGIN, token=issued["execution_control"]["token"]
    )
    args = dict(
        job_id="job-1", body=body, contract_id=row.id, attempt_id=row.attempt_id, fence=row.fence
    )
    current = s["service"].current(s["db"], s["runner"], **args)
    assert current["authority_sha256"] == s["review"]["context"]["authority_sha256"]
    with pytest.raises(WireRefused, match="owned_contract_fence_required"):
        s["service"].current(s["db"], s["runner"], **{**args, "fence": 2})
    from routers.jobs import finish_execution, refresh_execution

    user = {"github_id": "owner-1", "scope": "runner"}
    with pytest.raises(HTTPException) as unsupported:
        refresh_execution("job-1", body, s["runner"], user, s["db"])
    assert unsupported.value.status_code == 409
    s["db"].rollback()
    with pytest.raises(HTTPException) as unsupported:
        finish_execution(
            "job-1",
            control.FinishControl(**body.model_dump(), outcome="completed"),
            s["runner"],
            user,
            s["db"],
        )
    assert unsupported.value.status_code == 409
    s["db"].rollback()
    from routers.authorizations import update_authorization
    from schemas import AuthorizationUpdate

    update_authorization(
        "eng-1", "auth-1", AuthorizationUpdate(status="revoked"), {**user, "scope": "full"}, s["db"]
    )
    with pytest.raises(WireRefused, match="authority_revision_changed"):
        s["service"].current(s["db"], s["runner"], **args)
    assert s["db"].get(Engagement, "eng-1").duration_allocated == 30
    assert s["db"].query(ManagedApproval).one().issued == 1


@pytest.mark.parametrize("object_type", ["enrollment", "key"])
def test_stale_session_cannot_hide_association_or_key_revocation(specimen, object_type):
    s = specimen
    model, identifier = (
        (ManagedEnrollment, "enrollment-1") if object_type == "enrollment" else (ApiKey, "key-1")
    )
    cached = s["db"].get(model, identifier)
    with Session(s["engine"]) as other:
        row = other.get(model, identifier)
        if object_type == "enrollment":
            row.revoked = True
        else:
            other.delete(row)
        other.commit()
    # Identity-map state has not itself been refreshed by the external mutation.
    assert cached.id == identifier
    if object_type == "enrollment":
        assert cached.revoked is False
    with pytest.raises(WireRefused, match="enrollment_unavailable|enrollment_key_unavailable"):
        register(s)
    unchanged(s)


def test_stale_approval_identity_cannot_hide_revocation(specimen):
    s = specimen
    register(s)
    s["db"].expire_on_commit = False  # A valid caller-held identity-map configuration.
    cached = s["db"].query(ManagedApproval).one()
    assert cached.revoked is False
    with Session(s["engine"]) as other:
        s["service"].revoke(other, s["owner"], job_id="job-1")
    assert cached.revoked is False
    with pytest.raises(WireRefused, match="approval_unavailable"):
        claim(s)
    unchanged(s)
    with pytest.raises(WireRefused, match="approval_unavailable"):
        register(s)
    unchanged(s)


def sqlite_writer_held(engine):
    with engine.connect() as probe:
        probe.exec_driver_sql("PRAGMA busy_timeout=1")
        try:
            probe.exec_driver_sql("BEGIN IMMEDIATE")
            return False
        except OperationalError as exc:
            assert "locked" in str(exc)
            return True
        finally:
            probe.rollback()
            probe.exec_driver_sql("PRAGMA busy_timeout=5000")
            probe.rollback()


def test_sqlite_authority_commit_after_projection_cannot_issue_stale_permission(specimen):
    s = specimen
    register(s)
    projected, release = threading.Event(), threading.Event()
    original = s["service"]._claim_permission

    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        projected.set()
        assert release.wait(10)
        return result

    def issue():
        with Session(s["engine"]) as db:
            return claim(s, db=db)

    def revoke():
        from routers.authorizations import update_authorization
        from schemas import AuthorizationUpdate

        with Session(s["engine"]) as db:
            return update_authorization(
                "eng-1",
                "auth-1",
                AuthorizationUpdate(status="revoked"),
                {"github_id": "owner-1", "scope": "full"},
                db,
            )

    with patch.object(s["service"], "_claim_permission", held), ThreadPoolExecutor(2) as pool:
        issued = pool.submit(issue)
        assert projected.wait(5)
        writer_held = sqlite_writer_held(s["engine"])
        changed = pool.submit(revoke)
        if not writer_held:
            changed.result(5)  # Reproduce actual earlier commit, not a mocked flag.
            release.set()
            with pytest.raises((WireRefused, IssuanceRefused)):
                issued.result(10)
            unchanged(s)
        else:
            assert not changed.done()
            release.set()
            issued.result(10)
            changed.result(10)
            s["db"].expire_all()
            assert s["db"].query(ManagedContract).count() == 1
            assert s["db"].get(Engagement, "eng-1").managed_authority_revision == 1


@pytest.mark.parametrize("limiting", ["target", "duration"])
def test_sqlite_distinct_jobs_do_not_overspend_cached_target_or_duration(specimen, limiting):
    s = specimen
    db = s["db"]
    eng = db.get(Engagement, "eng-1")
    eng.concurrency_limit = 2
    eng.target_limit, eng.duration_limit = (1, 60) if limiting == "target" else (2, 30)
    db.add(
        ScanJob(
            id="job-2",
            program_id="eng-1",
            owner_github_id="owner-1",
            tool_type="vardrgate_api_test",
            target_source="scope",
            config={"test_case_id": "case-1"},
            status="pending",
            authorization_contract_required=True,
        )
    )
    db.commit()
    for job in ("job-1", "job-2"):
        review = s["service"].review(
            db,
            s["owner"],
            job_id=job,
            enrollment_id="enrollment-1",
            authorization_id="auth-1",
            plan=s["plan"],
            expires_at=stamp(NOW + timedelta(minutes=1)),
            max_executions=2,
            max_duration_seconds=60,
            max_artifact_bytes=1000000,
            credential_grants=s["review"]["context"]["credential_grants"],
        )
        s["service"].register(
            db,
            s["owner"],
            job_id=job,
            enrollment_id="enrollment-1",
            authorization_id="auth-1",
            plan=s["plan"],
            approval=signed(review["context"], "approval-" + job),
        )
    first, second, release = threading.Event(), threading.Event(), threading.Event()
    original = s["service"]._claim_permission
    retained_engagements = []

    def held(db, req, job, *args, **kwargs):
        # Retain a strong per-session identity across the writer wait; otherwise
        # SQLAlchemy's weak identity map can refresh away the actual stale cache.
        retained_engagements.append(db.get(Engagement, job.program_id))
        result = original(db, req, job, *args, **kwargs)
        if job.id == "job-1":
            first.set()
            assert release.wait(10)
        else:
            second.set()
        return result

    def issue(job):
        with Session(s["engine"]) as session:
            try:
                s["service"].claim(session, s["runner"], job_id=job, body=s["body"])
                return True
            except (WireRefused, HTTPException):
                return False

    with patch.object(s["service"], "_claim_permission", held), ThreadPoolExecutor(2) as pool:
        a = pool.submit(issue, "job-1")
        assert first.wait(5)
        writer_held = sqlite_writer_held(s["engine"])
        b = pool.submit(issue, "job-2")
        if not writer_held:
            assert second.wait(5), "unserialized second reader never reached authority projection"
            b.result(10)
        release.set()
        assert sum([a.result(10), b.result(10)]) == 1
    db.expire_all()
    assert db.query(ManagedContract).count() == db.query(JobExecution).count() == 1
    assert sum(row.issued for row in db.query(ManagedApproval)) == 1
    assert db.get(Engagement, "eng-1").targets_spent == 1
    assert db.get(Engagement, "eng-1").duration_allocated == 30
    assert len(retained_engagements) == 2


def test_concurrent_scope_writes_never_lose_authority_revision(specimen):
    s = specimen
    import managed_authority
    from routers.scope import add_out_scope_item
    from schemas import ScopeItemCreate

    first, second, release = threading.Event(), threading.Event(), threading.Event()
    original = managed_authority.lock

    def held(db, engagement):
        result = original(db, engagement)
        if threading.current_thread().name.endswith("_0"):
            first.set()
            assert release.wait(10)
        else:
            second.set()
        return result

    def write(value):
        with Session(s["engine"]) as db:
            return add_out_scope_item(
                "eng-1",
                ScopeItemCreate(value=value, kind="url"),
                {"github_id": "owner-1", "scope": "full"},
                db,
            )

    with patch.object(managed_authority, "lock", held), ThreadPoolExecutor(2) as pool:
        a = pool.submit(write, "https://one.example.test")
        assert first.wait(5)
        writer_held = sqlite_writer_held(s["engine"])
        b = pool.submit(write, "https://two.example.test")
        if not writer_held:
            assert second.wait(5)
            b.result(10)
        release.set()
        a.result(10)
        b.result(10)
    s["db"].expire_all()
    assert s["db"].get(Engagement, "eng-1").managed_authority_revision == 2


def test_legacy_claim_cas_rejects_new_requirement_even_with_stale_job_identity(specimen):
    s = specimen
    from routers.jobs import claim_job

    db = s["db"]
    db.add(
        ScanJob(
            id="legacy-job",
            program_id="eng-1",
            owner_github_id="owner-1",
            tool_type="vardrgate_api_test",
            target_source="scope",
            config={"test_case_id": "case-1"},
            status="pending",
            authorization_contract_required=False,
        )
    )
    db.commit()
    with Session(s["engine"], expire_on_commit=False) as legacy:
        stale = legacy.get(ScanJob, "legacy-job")
        assert stale.authorization_contract_required is False
        with Session(s["engine"]) as owner:
            review = s["service"].review(
                owner,
                s["owner"],
                job_id="legacy-job",
                enrollment_id="enrollment-1",
                authorization_id="auth-1",
                plan=s["plan"],
                expires_at=stamp(NOW + timedelta(minutes=1)),
                max_executions=2,
                max_duration_seconds=60,
                max_artifact_bytes=1000000,
                credential_grants=s["review"]["context"]["credential_grants"],
            )
            s["service"].register(
                owner,
                s["owner"],
                job_id="legacy-job",
                enrollment_id="enrollment-1",
                authorization_id="auth-1",
                plan=s["plan"],
                approval=signed(review["context"], "converted-job"),
            )
        assert stale.authorization_contract_required is False
        with pytest.raises(HTTPException) as denied:
            claim_job(
                "legacy-job",
                s["runner"],
                s["body"],
                {"github_id": "owner-1", "scope": "runner"},
                legacy,
            )
        assert denied.value.status_code == 409
    db.expire_all()
    assert db.get(ScanJob, "legacy-job").authorization_contract_required is True
    assert db.get(ScanJob, "legacy-job").status == "pending"
    assert db.query(ManagedContract).count() == db.query(JobExecution).count() == 0
    assert (
        db.get(Engagement, "eng-1").duration_allocated
        == db.get(Engagement, "eng-1").targets_spent
        == 0
    )


@pytest.mark.parametrize("boundary", ["helper", "issuer"])
def test_unknown_flushed_sqlite_transaction_is_refused_without_data_loss(specimen, boundary):
    s = specimen
    import managed_authority

    db = s["db"]
    pending = ScopeItem(
        program_id="eng-1", value="https://uncommitted.example.test", kind="url", scope_type="out"
    )
    db.add(pending)
    db.flush()
    ident = pending.id
    transaction = db.get_transaction()
    assert not db.new and not db.dirty and not db.deleted
    with pytest.raises(
        RuntimeError, match="unowned_sqlite_transaction|clean_sqlite_issuer_session_required"
    ):
        managed_authority.begin_write(db) if boundary == "helper" else register(s)
    assert db.get_transaction() is transaction and transaction.is_active
    assert db.get(ScopeItem, ident) is pending
    with Session(s["engine"]) as observer:
        assert observer.get(ScopeItem, ident) is None
    db.commit()  # Caller chooses disposition; boundary did not commit/discard it.
    with Session(s["engine"]) as observer:
        assert observer.get(ScopeItem, ident) is not None
