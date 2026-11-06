"""Real ASGI admission/retirement protocol, not Docker termination attestation."""

import hashlib
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from execution_control import ControlRequest
from managed_http import build_managed_router
from managed_observations import Observations
from managed_results import Results
from managed_runtime import Runtimes, capability_hash
from managed_runtime_http import build_runtime_router
from managed_wire import digest
from models import (
    ApiKey,
    Engagement,
    JobExecution,
    ManagedApproval,
    ManagedContract,
    ManagedEnrollment,
    ManagedResult,
    ManagedRuntime,
    ManagedStop,
    ScanJob,
)
from sqlalchemy import event
from sqlalchemy.orm import Session
from routers.local_auth import router as local_router
from tests import test_managed_http_boundary as runtime
from tests import test_managed_receipt_http as receipt
from tests.test_managed_issuance import KEY, RUNNER, mint_token
from tests.test_managed_issuance import specimen as specimen
from tests.test_managed_approval_http import login

runtime_http = runtime.http
SECRET = "0123456789abcdef" * 4
RUNTIME_ID = "00000000-0000-0000-0000-000000000011"
PATH = "/managed/runtimes/" + RUNTIME_ID


@pytest.fixture
def http(runtime_http):
    h = runtime_http
    h.results = Results(h.s["service"])
    h.runtimes = Runtimes(h.results)
    # Explicit separate ASGI app; product main remains unchanged/unregistered.
    dependencies = dict(h.app.dependency_overrides)
    h.app = FastAPI()
    h.app.dependency_overrides.update(dependencies)
    h.app.include_router(local_router)
    h.app.include_router(build_managed_router(h.s["service"], h.runtimes))
    h.app.include_router(build_runtime_router(h.runtimes))
    h.app.include_router(receipt.boundary.build_receipt_router(h.results))
    h.owner = {"Authorization": "Bearer " + mint_token("owner-1")}
    h.host = {"Authorization": "VardrStop " + SECRET}
    h.identity = dict(
        daemon_id="daemon-fixture",
        container_id="1" * 64,
        image_id="sha256:" + "2" * 64,
        project="managed-worker",
        started_at="2026-11-02T17:59:00.000000001Z",
        owner_nonce="3" * 64,
    )
    h.sha = digest(h.identity)
    h.registration = dict(
        enrollment_id="enrollment-1",
        runner_id=RUNNER,
        origin=runtime.ORIGIN,
        identity=h.identity,
        capability_sha256=capability_hash(SECRET),
        expires_in_seconds=3600,
    )
    with TestClient(h.app, base_url=runtime.ORIGIN) as client:
        h.client = client
        yield h


def post(h, suffix, body, headers=None):
    return h.client.post(
        PATH + suffix, json=body, headers=h.host if headers is None else headers
    )


def register(h):
    reply = post(h, "/register", h.registration, h.owner)
    assert reply.status_code == 200, reply.text
    return reply.json()


def claim(h):
    register(h)
    reply = h.client.post(
        "/jobs/job-1/managed/claim",
        json={**h.body, "runtime_id": RUNTIME_ID, "runtime_sha256": h.sha},
        headers=h.headers,
    )
    assert reply.status_code == 200, reply.text
    with Session(h.s["engine"]) as db:
        c = db.query(ManagedContract).one()
        h.owned = {
            **h.pending,
            "token": reply.json()["execution_control"]["token"],
            "contract_id": c.id,
            "attempt_id": c.attempt_id,
            "fence": c.fence,
            "contract_sha256": digest(c.envelope),
        }
    return reply


def consume(h):
    reply = h.client.post(
        "/jobs/job-1/managed/consume", json=h.owned, headers=h.headers
    )
    assert reply.status_code == 200, reply.text
    return reply.json()


def confirm(h):
    return h.client.post(
        "/jobs/job-1/managed/runtime-bind",
        json={**h.owned, "runtime_id": RUNTIME_ID, "runtime_sha256": h.sha},
        headers=h.headers,
    )


def lookup(h):
    return post(h, "/receipt", {"runtime_sha256": h.sha})


def observed(h):
    reply = lookup(h)
    assert reply.status_code == 200
    binding = reply.json()["binding"]
    assert binding is not None
    return {
        "runtime_sha256": h.sha,
        **binding,
        "finished_at": "2026-11-02T18:00:01.123456789Z",
        "exit_code": 137,
        "observation_sha256": "4" * 64,
    }


def state(h):
    with Session(h.s["engine"]) as db:
        j, e = db.get(ScanJob, "job-1"), db.get(Engagement, "eng-1")
        x, c = db.get(JobExecution, "job-1"), db.query(ManagedContract).first()
        r = db.get(ManagedRuntime, RUNTIME_ID)
        return (
            j.status,
            e.targets_spent,
            e.duration_allocated,
            db.query(ManagedApproval).one().issued,
            c.consumed if c else None,
            (x.state, x.capacity_reserved) if x else None,
            db.query(ManagedStop).count(),
            db.query(ManagedResult).count(),
            (r.contract_id, r.confirmed_at, r.retired, r.report_sha256) if r else None,
        )


def test_registration_replay_cannot_extend_or_replace_public_admission(http):
    h = http
    first = register(h)
    assert first == {
        "schema": "vardr.worker-admission/1",
        "runtime_id": RUNTIME_ID,
        "runtime_sha256": h.sha,
        "enrollment_id": "enrollment-1",
        "runner_id": RUNNER,
        "origin": runtime.ORIGIN,
        "capability_sha256": capability_hash(SECRET),
        "identity": h.identity,
        "expires_at": "2026-11-02T19:00:00Z",
    }
    h.s["wall"][0] += timedelta(seconds=1)
    assert register(h) == first
    changed = {**h.registration, "expires_in_seconds": 3601}
    assert post(h, "/register", changed, h.owner).status_code == 409
    with Session(h.s["engine"]) as db:
        row = db.get(ManagedRuntime, RUNTIME_ID)
        assert SECRET not in repr(row.__dict__) and row.ttl_seconds == 3600
    assert state(h)[1:8] == (0, 0, 0, None, None, 0, 0)


@pytest.mark.parametrize("kind", ["key", "full_key", "foreign_owner"])
def test_registration_requires_the_existing_human_owner_session(http, kind):
    h = http
    headers = h.headers
    if kind == "full_key":
        with Session(h.s["engine"]) as db:
            db.get(ApiKey, "key-1").scope = "full"
            db.commit()
    elif kind == "foreign_owner":
        headers = {"Authorization": "Bearer " + mint_token("other")}
    assert post(h, "/register", h.registration, headers).status_code == 409
    assert state(h)[-1] is None


def test_atomic_claim_associates_the_issued_attempt_before_any_consumption_reply(http):
    h = http
    claim(h)
    before = state(h)
    assert before[1:6] == (1, 30, 1, False, ("active", True))
    assert before[-1][0] is not None and before[-1][1] is None
    observed_binding = lookup(h).json()
    assert observed_binding["binding"]["contract_id"] == h.owned["contract_id"]
    assert observed_binding["receipt"] is None and '"token"' not in lookup(h).text
    assert confirm(h).status_code == 409 and state(h) == before
    consume(h)
    confirmed = confirm(h)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json() == {
        "schema": "vardr.worker-runtime-binding/1",
        **{key: value for key, value in h.owned.items() if key != "token"},
        "job_id": "job-1",
        "runtime_id": RUNTIME_ID,
        "runtime_sha256": h.sha,
        "bound": True,
    }
    assert confirm(h).status_code == 409


@pytest.mark.parametrize("change", ["runtime_sha", "revoked", "missing"])
def test_runtime_denial_rolls_back_the_entire_claim_including_spend(http, change):
    h = http
    register(h)
    body = {**h.body, "runtime_id": RUNTIME_ID, "runtime_sha256": h.sha}
    if change == "runtime_sha":
        body["runtime_sha256"] = "0" * 64
    elif change == "missing":
        body["runtime_id"] = "00000000-0000-0000-0000-000000000099"
    else:
        assert post(h, "/revoke", {}, h.owner).status_code == 200
    before = state(h)
    reply = h.client.post("/jobs/job-1/managed/claim", json=body, headers=h.headers)
    assert reply.status_code == 409 and state(h) == before


@pytest.mark.parametrize("consumed", [False, True])
def test_lost_claim_or_consume_reply_can_retire_the_exact_exited_runtime_without_fake_ack(
    http, consumed
):
    h = http
    claim(h)
    if consumed:
        consume(h)
    intent = observed(h)
    reply = post(h, "/observed-exit", intent)
    assert reply.status_code == 200, reply.text
    ack = reply.json()
    assert (
        ack["receipt"]["outcome"] == "failed"
        and ack["receipt"]["cause"] == "observed_exit"
    )
    terminal = state(h)
    assert terminal[:8] == ("failed", 1, 30, 1, consumed, ("failed", False), 1, 0)
    assert terminal[-1][2] is True and terminal[-1][3] is not None
    assert lookup(h).json()["receipt"] == ack["receipt"]
    assert post(h, "/observed-exit", intent).json() == ack
    assert state(h) == terminal
    # Original tokens cannot revive even an unconsumed but physically retired attempt.
    for action, body in (
        ("consume", h.owned),
        ("refresh", {k: v for k, v in h.owned.items() if k != "contract_sha256"}),
    ):
        assert (
            h.client.post(
                "/jobs/job-1/managed/" + action, json=body, headers=h.headers
            ).status_code
            == 409
        )
    assert confirm(h).status_code == 409
    if not consumed:
        observer = Observations(h.results)
        with Session(h.s["engine"]) as db:
            reply = observer.inspect(
                db,
                h.s["runner"],
                job_id="job-1",
                body=h.s["body"],
                plan_sha256=digest(h.s["plan"]),
                case_sha256=h.s["plan"]["case_hash"],
                association_sha256=digest(
                    {
                        "origin": runtime.ORIGIN,
                        "runner_id": RUNNER,
                        "principal_sha256": hashlib.sha256(
                            ("Bearer " + KEY).encode()
                        ).hexdigest(),
                    }
                ),
            )
        assert reply["claim"]["consumed"] is False
        assert reply["stop"] == ack["receipt"] and reply["capacity_reserved"] is False


@pytest.mark.parametrize(
    "change", ["enrollment_revoke", "key_delete", "approval_revoke"]
)
def test_independent_live_stop_grant_survives_execution_authority_revocation(
    http, change
):
    h = http
    claim(h)
    with Session(h.s["engine"]) as db:
        if change == "enrollment_revoke":
            row = db.get(ManagedEnrollment, "enrollment-1")
            row.revoked, row.revision = True, row.revision + 1
        elif change == "key_delete":
            db.delete(db.get(ApiKey, "key-1"))
        else:
            db.query(ManagedApproval).one().revoked = True
        db.commit()
    reply = post(h, "/observed-exit", observed(h))
    assert reply.status_code == 200 and state(h)[5] == ("failed", False)


@pytest.mark.parametrize("change", ["expired", "revoked"])
def test_expired_or_revoked_grant_blocks_new_report_but_keeps_exact_final_receipt_readable(
    http, change
):
    h = http
    claim(h)
    intent = observed(h)
    accepted = post(h, "/observed-exit", intent)
    assert accepted.status_code == 200
    before = state(h)
    if change == "expired":
        h.s["wall"][0] += timedelta(seconds=3601)
    else:
        assert post(h, "/revoke", {}, h.owner).status_code == 200
    assert post(h, "/observed-exit", intent).status_code == 409
    assert (
        lookup(h).json()["receipt"] == accepted.json()["receipt"] and state(h) == before
    )


def pending_result(h):
    claimed = claim(h).json()
    consume(h)
    assert confirm(h).status_code == 200
    h.raw = {
        "test_case_id": "case-1",
        "case_hash": h.s["plan"]["case_hash"],
        "executions": [
            {
                "identity_id": claimed["config"]["test_case"]["identities"][0]["id"],
                "status_code": 200,
                "observed_outcome": "allow",
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
    result = h.client.post(
        "/jobs/job-1/managed/result", json=receipt.artifact(h), headers=h.headers
    )
    assert result.status_code == 200, result.text
    return result.json()


def retained_rows(h):
    with Session(h.s["engine"]) as db:
        return tuple(
            tuple(db.execute(model.__table__.select().order_by(model.id)).all())
            for model in (receipt.Evidence, receipt.ScanItem, receipt.JobResultReceipt)
        )


@pytest.mark.parametrize(
    "authority",
    ["live", "lease_expired", "enrollment_revoked", "key_deleted", "approval_revoked"],
)
def test_exited_runtime_fails_the_retained_result_without_replacing_evidence_or_refunding(
    http, authority
):
    h = http
    ack = pending_result(h)
    retained = receipt.state(h)
    evidence = retained_rows(h)
    if authority == "lease_expired":
        h.s["wall"][0] += timedelta(seconds=11)
    elif authority != "live":
        with Session(h.s["engine"]) as db:
            if authority == "enrollment_revoked":
                row = db.get(ManagedEnrollment, "enrollment-1")
                row.revoked, row.revision = True, row.revision + 1
            elif authority == "key_deleted":
                db.delete(db.get(ApiKey, "key-1"))
            else:
                db.query(ManagedApproval).one().revoked = True
            db.commit()
    intent = observed(h)
    reply = post(h, "/observed-exit", intent)
    assert reply.status_code == 200, reply.text
    completion = reply.json()["receipt"]
    assert completion == {
        "schema": "vardr.managed-completion/1",
        **lookup(h).json()["binding"],
        "receipt_sha256": ack["receipt_sha256"],
        "outcome": "failed",
        "capacity_reserved": False,
    }
    after = receipt.state(h)
    assert after == {
        **retained,
        "job": "failed",
        "execution": "failed",
        "capacity": False,
        "results": [(ack["receipt_sha256"], ack["artifact_sha256"], "failed")],
    }
    assert after["evidence"] == after["candidates"] == after["legacy_receipts"] == 1
    assert after["stops"] == [] and state(h)[-1][2] is True
    assert post(h, "/observed-exit", intent).json() == reply.json()
    assert post(h, "/observed-exit", {**intent, "exit_code": 1}).status_code == 409
    assert lookup(h).json()["receipt"] == completion and receipt.state(h) == after
    assert retained_rows(h) == evidence
    if authority == "live":
        original = receipt.post(h, "/result")
        assert original.json() == ack
        with Session(h.s["engine"]) as db:
            observed_result = h.results.inspect(
                db,
                h.s["runner"],
                job_id="job-1",
                body=ControlRequest(
                    origin=runtime.ORIGIN, runner_id=RUNNER, token=h.owned["token"]
                ),
                **{
                    k: h.owned[k]
                    for k in ("contract_id", "attempt_id", "fence", "contract_sha256")
                },
            )
        assert observed_result["result"] == ack
        assert observed_result["completion"] == completion
        assert observed_result["consumed"] is True
        assert (
            receipt.post(h, "/finish", receipt.finish_body(h, ack)).status_code == 409
        )


@pytest.mark.parametrize("change", ["expired", "revoked"])
def test_failed_result_receipt_remains_readable_after_stop_grant_retirement(
    http, change
):
    h = http
    pending_result(h)
    intent = observed(h)
    accepted = post(h, "/observed-exit", intent)
    assert accepted.status_code == 200
    before = state(h)
    if change == "expired":
        h.s["wall"][0] += timedelta(seconds=3601)
    else:
        assert post(h, "/revoke", {}, h.owner).status_code == 200
    assert post(h, "/observed-exit", intent).status_code == 409
    assert lookup(h).json()["receipt"] == accepted.json()["receipt"]
    assert state(h) == before


@pytest.mark.parametrize("outcome", ["completed", "cancelled", "failed"])
def test_host_cannot_replace_an_existing_native_result_completion(http, outcome):
    h = http
    ack = pending_result(h)
    native = receipt.post(h, "/finish", receipt.finish_body(h, ack, outcome))
    assert native.status_code == 200, native.text
    before = state(h)
    assert post(h, "/observed-exit", observed(h)).status_code == 409
    assert lookup(h).json()["receipt"] == native.json() and state(h) == before


@pytest.mark.parametrize(
    "change", ["runtime_sha", "attempt", "enrollment_identity", "wrong_secret"]
)
def test_changed_identity_or_secret_never_releases_the_bound_attempt(http, change):
    h = http
    claim(h)
    intent, headers = observed(h), h.host
    if change == "runtime_sha":
        intent["runtime_sha256"] = "0" * 64
    elif change == "attempt":
        intent["attempt_id"] = "00000000-0000-0000-0000-000000000099"
    elif change == "wrong_secret":
        headers = {"Authorization": "VardrStop " + "f" * 64}
    else:
        with Session(h.s["engine"]) as db:
            db.get(
                ManagedEnrollment, "enrollment-1"
            ).origin = "https://different.synthetic.test"
            db.commit()
    before = state(h)
    reply = post(h, "/observed-exit", intent, headers)
    assert (
        reply.status_code == (404 if change == "wrong_secret" else 409)
        and state(h) == before
    )


@pytest.mark.parametrize("result_uploaded", [False, True])
def test_failure_after_terminal_write_rolls_back_receipt_retirement_and_release_together(
    http, result_uploaded
):
    h = http
    if result_uploaded:
        pending_result(h)
    else:
        claim(h)
    intent, before = observed(h), state(h)

    def fault(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.startswith("UPDATE managed_runtimes")
            and "report_sha256" in statement
        ):
            raise RuntimeError("synthetic_do_not_echo")

    event.listen(h.s["engine"], "after_cursor_execute", fault)
    try:
        reply = post(h, "/observed-exit", intent)
    finally:
        event.remove(h.s["engine"], "after_cursor_execute", fault)
    assert reply.status_code == 503 and "synthetic_do_not_echo" not in reply.text
    assert state(h) == before


def test_runtime_factory_is_unregistered_and_cannot_reuse_host_authority_as_execution_auth(
    http,
):
    from main import app

    h = http
    register(h)
    paths = {r.path for r in build_runtime_router(h.runtimes).routes}
    assert paths.isdisjoint(app.openapi()["paths"])
    before = state(h)
    reply = h.client.post("/jobs/job-1/managed/claim", json=h.body, headers=h.host)
    assert reply.status_code == 401 and state(h) == before


def test_local_owner_registration_and_revocation_keep_existing_csrf(http):
    h = http
    headers = login(h)
    missing = {key: value for key, value in headers.items() if key != "X-CSRF-Token"}
    assert post(h, "/register", h.registration, missing).status_code == 403
    assert state(h)[-1] is None
    assert post(h, "/register", h.registration, headers).status_code == 200
    assert post(h, "/revoke", {}, missing).status_code == 403
    assert post(h, "/revoke", {}, headers).status_code == 200


@pytest.mark.parametrize("change", ["physical_alias", "nonce_reuse", "secret_reuse"])
def test_registration_uniqueness_rejects_aliases_or_reused_authority(http, change):
    h = http
    if change == "physical_alias":
        h.identity["started_at"] = "2026-11-02T17:59:00.1Z"
        h.sha = digest(h.identity)
    register(h)
    altered = {
        **h.registration,
        "identity": {**h.identity, "container_id": "8" * 64, "owner_nonce": "9" * 64},
        "capability_sha256": capability_hash("a" * 64),
    }
    if change == "physical_alias":
        altered["identity"] = {
            **h.identity,
            "owner_nonce": "9" * 64,
            "started_at": "2026-11-02T17:59:00.100000000Z",
        }
    elif change == "nonce_reuse":
        altered["identity"]["owner_nonce"] = h.identity["owner_nonce"]
    else:
        altered["capability_sha256"] = h.registration["capability_sha256"]
    reply = h.client.post(
        "/managed/runtimes/00000000-0000-0000-0000-000000000012/register",
        json=altered,
        headers=h.owner,
    )
    assert reply.status_code == 409
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedRuntime).count() == 1


def test_distinct_nanosecond_start_is_a_distinct_incarnation_in_database(http):
    h = http
    register(h)
    altered = {
        **h.registration,
        "identity": {
            **h.identity,
            "started_at": "2026-11-02T17:59:00.000000002Z",
            "owner_nonce": "9" * 64,
        },
        "capability_sha256": capability_hash("a" * 64),
    }
    reply = h.client.post(
        "/managed/runtimes/00000000-0000-0000-0000-000000000012/register",
        json=altered,
        headers=h.owner,
    )
    assert reply.status_code == 200
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedRuntime).count() == 2


@pytest.mark.parametrize("change", ["expired", "revoked"])
@pytest.mark.parametrize("result_uploaded", [False, True])
def test_expired_or_revoked_grant_cannot_create_the_first_terminal_receipt(
    http, change, result_uploaded
):
    h = http
    if result_uploaded:
        pending_result(h)
    else:
        claim(h)
    intent = observed(h)
    if change == "expired":
        h.s["wall"][0] += timedelta(seconds=3601)
    else:
        assert post(h, "/revoke", {}, h.owner).status_code == 200
    before = state(h)
    assert post(h, "/observed-exit", intent).status_code == 409
    assert state(h) == before and before[5] == ("active", True) and before[6] == 0
    assert lookup(h).json()["receipt"] is None


def test_native_producer_cannot_assert_the_host_only_observed_exit_cause(http):
    h = http
    claim(h)
    consume(h)
    assert confirm(h).status_code == 200
    before = state(h)
    body = {
        **h.owned,
        "cause": "observed_exit",
        "outcome": "failed",
        "termination_confirmed": True,
    }
    reply = h.client.post("/jobs/job-1/managed/stopped", json=body, headers=h.headers)
    assert reply.status_code == 409 and state(h) == before


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("cause", "local_emergency_stop", 422),
        ("outcome", "completed", 422),
        ("token", "synthetic_do_not_echo", 422),
        ("exit_code", True, 422),
        ("finished_at", "2026-11-02T17:58:00Z", 409),
    ],
)
def test_host_report_has_fixed_failure_semantics_and_no_native_token_input(
    http, field, value, status
):
    h = http
    claim(h)
    intent = {**observed(h), field: value}
    before = state(h)
    reply = post(h, "/observed-exit", intent)
    assert reply.status_code == status and state(h) == before
    assert "synthetic_do_not_echo" not in reply.text


@pytest.mark.parametrize("prefix", ["Bearer  ", "Bearer \t"])
def test_normalized_full_api_key_cannot_register_host_reporting_authority(http, prefix):
    h = http
    with Session(h.s["engine"]) as db:
        db.get(ApiKey, "key-1").scope = "full"
        db.commit()
    before = state(h)
    reply = post(h, "/register", h.registration, {"Authorization": prefix + KEY})
    assert reply.status_code == 409 and state(h) == before
    assert reply.json() == {"detail": "managed_runtime_refused"}
