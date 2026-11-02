"""Read-only approval projections over disposable ORM state, with no new routes."""

import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from assessments import case_hash
from db import Base
from models import Authorization, AuthorizationTestCase, Engagement, ScanJob, ScopeItem
from nm1_authorization import IssuanceRefused, prepare_approval_request


@pytest.fixture
def request_fixture():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 11, 1, 18, tzinfo=timezone.utc)
    with Session(engine) as db:
        engagement = Engagement(
            id="eng-1",
            owner_github_id="operator-1",
            name="Synthetic NM1",
            engagement_type="pentest",
            engagement_status="active",
        )
        authority = Authorization(
            id="auth-1",
            program_id="eng-1",
            owner_github_id="operator-1",
            permits="Synthetic controlled fixture only",
            status="active",
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(hours=1),
        )
        case = AuthorizationTestCase(
            id="case-1",
            program_id="eng-1",
            owner_github_id="operator-1",
            name="Synthetic",
            spec={
                "id": "t",
                "request": {
                    "method": "GET",
                    "url": "https://api.example.test/objects/1",
                },
            },
        )
        job = ScanJob(
            id="job-1",
            program_id="eng-1",
            owner_github_id="operator-1",
            tool_type="vardrgate_api_test",
            target_source="scope",
            config={"test_case_id": "case-1"},
            status="pending",
        )
        scope = ScopeItem(
            program_id="eng-1",
            value="https://api.example.test",
            kind="url",
            scope_type="in",
        )
        db.add_all([engagement, authority, case, job, scope])
        db.commit()
        plan = {
            "schema": "vardr.execution-plan/1",
            "profile": "gate-fixed-http/1",
            "case_hash": case_hash(case.spec),
            "max_http_dispatches": 1,
            "dispatches": [{"request": case.spec["request"]}],
        }
        arguments = dict(
            job_id="job-1",
            authorization_id="auth-1",
            actor={
                "github_id": "operator-1",
                "scope": "full",
                "auth_method": "local_session",
            },
            plan=plan,
            runner_id="runner-1",
            authority_revision=1,
            expires_at=now + timedelta(minutes=10),
            max_executions=3,
            max_duration_seconds=60,
            max_artifact_bytes=1000000,
            credential_grants=[],
            now=now,
        )
        yield db, arguments, engagement, authority, case, job, scope
    engine.dispose()


def test_owner_snapshot_is_bounded_reusable_and_read_only(request_fixture):
    db, arguments, *objects = request_fixture
    result = prepare_approval_request(db, **arguments)
    assert result["context"]["max_executions"] == 3
    assert result["context"]["control"] == "managed_online"
    assert result["context"]["scope"][0]["path"] == "/objects/1"
    assert not db.dirty and not db.new
    assert objects[3].status == "pending" and objects[3].case_snapshot is None


@pytest.mark.parametrize(
    "actor",
    [
        {"github_id": "operator-1", "scope": "full", "auth_method": "api_key"},
        {"github_id": "operator-1", "scope": "runner", "auth_method": "local_session"},
        {"github_id": "other", "scope": "full", "auth_method": "local_session"},
        {"github_id": "operator-1", "scope": "full", "reviewed": True},
    ],
)
def test_ai_or_key_or_nonowner_cannot_approve(request_fixture, actor):
    db, arguments, *_ = request_fixture
    with pytest.raises(IssuanceRefused):
        prepare_approval_request(db, **{**arguments, "actor": actor})


@pytest.mark.parametrize(
    "change",
    [
        "revoked",
        "stopped",
        "case",
        "auxiliary",
        "scope",
        "count",
        "expired",
        "wrong_authority",
        "running",
    ],
)
def test_changed_or_unpermitted_context_refused(request_fixture, change):
    db, arguments, engagement, authority, case, job, scope = request_fixture
    arguments = copy.deepcopy(arguments)
    if change == "revoked":
        authority.status = "revoked"
    elif change == "stopped":
        engagement.stop_work_at = arguments["now"]
    elif change == "case":
        case.spec = {**case.spec, "description": "edited"}
    elif change == "auxiliary":
        arguments["plan"]["dispatches"].append(
            {"request": {"method": "POST", "url": "https://outside.invalid/reset"}}
        )
    elif change == "scope":
        scope.scope_type = "out"
    elif change == "count":
        arguments["max_executions"] = True
    elif change == "expired":
        arguments["expires_at"] = arguments["now"] - timedelta(seconds=1)
    elif change == "wrong_authority":
        arguments["authorization_id"] = "other"
    else:
        job.status = "running"
    db.flush()
    with pytest.raises(IssuanceRefused):
        prepare_approval_request(db, **arguments)


def test_snapshot_changes_when_permission_text_changes(request_fixture):
    db, arguments, _, authority, *_ = request_fixture
    first = prepare_approval_request(db, **arguments)
    authority.permits = "Changed permission requires new review"
    db.flush()
    second = prepare_approval_request(db, **arguments)
    assert first["context"]["authority_sha256"] != second["context"]["authority_sha256"]
