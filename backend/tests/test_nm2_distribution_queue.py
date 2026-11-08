"""Opt-in public Distribution queue contract; ASGI only, no tool execution.

Set NM2_DISTRIBUTION_SOURCE and NM2_RUNNER_SOURCE to explicit checkout directories.
This checks queueing and real approval review/registration, not execution or TLS.
"""

import importlib.util
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import managed_enrollment
import policy
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from db import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from managed_approval_http import build_approval_router
from managed_issuance import Issuer
from managed_wire import ContractWire, OperatorAnchor
from models import (
    Authorization,
    Engagement,
    JobExecution,
    ManagedApproval,
    ManagedContract,
    ManagedEnrollment,
    ScanJob,
    ScopeItem,
)


@pytest.mark.parametrize("in_scope", [True, False], ids=["happy", "strict-denial"])
def test_distribution_queue_uses_supported_flat_config_and_separate_review_plan(
    client, auth_headers, monkeypatch, in_scope
):
    distribution = os.environ.get("NM2_DISTRIBUTION_SOURCE")
    runner = os.environ.get("NM2_RUNNER_SOURCE")
    if not distribution:
        pytest.skip("explicit Distribution source directory required")
    assert runner, "NM2_RUNNER_SOURCE is required with opted-in Distribution source"
    distribution, runner = Path(distribution), Path(runner)
    assert distribution.is_absolute() and runner.is_absolute()
    source = distribution / "tests" / "nm2_worker_acceptance.py"
    assert (
        source.is_file()
        and (runner / "vardrrunner" / "authorization" / "plan.py").is_file()
    )
    monkeypatch.syspath_prepend(str(distribution / "tests"))
    monkeypatch.syspath_prepend(str(runner))
    spec = importlib.util.spec_from_file_location(
        "nm2_public_distribution_queue", source
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def no_command(*args, **kwargs):
        pytest.fail("queue preparation must not invoke Docker or another process")

    monkeypatch.setattr(module, "command", no_command)

    class API:
        engagement_id = None
        managed = None
        review = None

        def request(self, path, body=None, *, method=None, expected=200):
            target = self.managed if "/managed/approval/" in path else client
            response = target.request(
                method or ("POST" if body is not None else "GET"),
                path,
                headers=auth_headers,
                **({"json": body} if body is not None else {}),
            )
            assert response.status_code == expected, response.text
            reply = response.json()
            if path == "/engagements" and body is not None:
                self.engagement_id = reply["id"]
            if path.endswith("/approval/review"):
                self.review = (body, reply)
            return reply

    api = API()
    # Exercise the public method without invoking its unrelated Docker setup.
    fixture = module.Fixture.__new__(module.Fixture)
    fixture.api = api
    fixture.project = "vardrsec-nm2-asgiqueue"
    fixture.owner = "gh_user1"
    fixture.issuer_origin = "https://map.distribution-fixture.test"
    fixture.issuer_id = "distribution-review-" + uuid.uuid4().hex
    fixture.operator_key = os.urandom(32)
    runner_id = str(uuid.uuid4())
    fixture.key = api.request(
        "/auth/apikeys", {"label": "Disposable review fixture", "scope": "runner"}
    )
    database = client.app.dependency_overrides[get_db]

    def helper(*args, python=False):
        # Replace only container-local identity/hash/grant commands. The actual
        # fixture still compiles, reviews, signs and registers through real APIs.
        if args == ("identity", "show") and not python:
            return ("Runner ID: " + runner_id).encode()
        if args[:2] == ("credentials", "approve") and not python:
            assert args[args.index("--origin") + 1] == module.ORIGIN
            assert args[args.index("--env") + 1] in {
                "FIXTURE_OWNER_TOKEN",
                "FIXTURE_PEER_TOKEN",
            }
            return b""
        assert python and args[:2] == ("-I", "-c")
        assert "/usr/local/bin/vardrgate" in args[2]
        return b"a" * 64

    def bind(*args, stdin):
        assert args[:7] == (
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "managed_enrollment",
            "bind",
        )
        assert args[-1] == "--key-stdin"
        with next_database() as db:
            reply = managed_enrollment.bind(
                db,
                owner=args[args.index("--owner") + 1],
                api_key_id=args[args.index("--api-key-id") + 1],
                runner_id=args[args.index("--runner-id") + 1],
                origin=args[args.index("--origin") + 1],
                key=stdin.decode().strip(),
            )
        return json.dumps(reply).encode()

    @contextmanager
    def next_database():
        dependency = database()
        try:
            yield next(dependency)
        finally:
            dependency.close()

    fixture.helper, fixture.compose = helper, bind
    wire = ContractWire(
        fixture.issuer_id,
        "contract",
        os.urandom(32),
        (
            OperatorAnchor(
                fixture.issuer_id,
                "operator",
                fixture.owner,
                Ed25519PrivateKey.from_private_bytes(fixture.operator_key)
                .public_key()
                .public_bytes_raw(),
            ),
        ),
    )
    app = FastAPI()
    app.dependency_overrides[get_db] = database
    app.include_router(build_approval_router(Issuer(fixture.issuer_origin, wire)))
    try:
        engagement, authorization, job_id, case = fixture.new_job(
            "asgi-queue", in_scope=in_scope
        )
        assert engagement == api.engagement_id and authorization
        jobs = api.request(f"/engagements/{engagement}/jobs")["jobs"]
        job = next(row for row in jobs if row["id"] == job_id)
        assert job["status"] == "pending"
        assert job["authorization_contract_required"] is True
        assert job["config"] == {"test_case_id": case["id"], "timeout": 20}
        from vardrrunner.authorization.plan import compile_gate_plan

        assert (
            Path(compile_gate_plan.__code__.co_filename).resolve()
            == (runner / "vardrrunner" / "authorization" / "plan.py").resolve()
        )
        plan = compile_gate_plan(case["spec"], module.EXECUTION, tool_sha256="a" * 64)
        assert plan["execution"] == {
            "timeout_seconds": 20,
            "max_response_bytes": 65536,
            "allow_private_targets": True,
        }
        assert "execution" not in job["config"]
        assert len(plan["dispatches"]) == 5
        assert {
            dispatch["request"]["url"].split("/", 3)[2]
            for dispatch in plan["dispatches"]
        } == {"gate-fixture.test:8080"}
        with next_database() as db:
            authority = db.get(Authorization, authorization)
            scope = db.query(ScopeItem).filter_by(program_id=engagement).all()
            engagement_row = db.get(Engagement, engagement)
            decisions = [
                policy.evaluate(
                    policy.PolicyInput(
                        engagement_status=engagement_row.engagement_status,
                        engagement_type=engagement_row.engagement_type,
                        target=dispatch["request"]["url"],
                        capability="vardrgate_api_test",
                        now=datetime.now(timezone.utc),
                        authorization=policy.AuthorizationSnapshot(
                            authority.status,
                            authority.window_start,
                            authority.window_end,
                        ),
                        scope_rules=tuple(
                            policy.ScopeRule(
                                value=row.value,
                                kind=row.kind,
                                excluded=row.scope_type == "out",
                            )
                            for row in scope
                        ),
                    )
                )
                for dispatch in plan["dispatches"]
            ]
            assert all(decision.allowed is in_scope for decision in decisions)
            assert {decision.reason for decision in decisions} == {
                policy.ALLOWED if in_scope else policy.TARGET_OUT_OF_SCOPE
            }
        with TestClient(app, base_url=fixture.issuer_origin) as managed:
            api.managed = managed
            binding = fixture.approve(
                "asgi-queue",
                engagement,
                authorization,
                job_id,
                case,
                expected=200 if in_scope else 409,
            )
        assert (binding is not None) is in_scope
        body, review = api.review
        assert body["plan"] == plan
        if in_scope:
            context = review["context"]
            assert context["max_http_dispatches"] == 5
            assert context["runner_id"] == runner_id
            assert context["max_executions"] == 1
            assert context["max_duration_seconds"] == 30
            assert context["max_artifact_bytes"] == 1024 * 1024
            assert len(context["scope"]) == 5
            assert {grant["name"] for grant in context["credential_grants"]} == {
                "FIXTURE_OWNER_TOKEN",
                "FIXTURE_PEER_TOKEN",
            }
        else:
            assert review == {"detail": "managed_approval_refused"}
        with next_database() as db:
            stored = db.get(ScanJob, job_id)
            assert stored.status == "pending" and stored.case_snapshot is None
            assert (stored.managed_approval_id is not None) is in_scope
            assert db.query(ManagedContract).filter_by(job_id=job_id).count() == 0
            assert db.query(JobExecution).filter_by(job_id=job_id).count() == 0
            engagement_row = db.get(Engagement, engagement)
            assert (
                engagement_row.targets_spent == engagement_row.duration_allocated == 0
            )
    finally:
        if api.engagement_id is not None:
            response = client.delete(
                f"/engagements/{api.engagement_id}", headers=auth_headers
            )
            assert response.status_code == 200, response.text
        with next_database() as db:
            db.query(ManagedApproval).filter_by(issuer=fixture.issuer_id).delete()
            db.query(ManagedEnrollment).filter_by(runner_id=runner_id).delete()
            db.commit()
        assert (
            client.delete(
                "/auth/apikeys/" + fixture.key["id"], headers=auth_headers
            ).status_code
            == 200
        )
