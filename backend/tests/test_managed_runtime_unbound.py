"""Unbound runtime retirement fences future claims; no process proof fabrication."""

from datetime import timedelta
import hashlib

import pytest
from managed_wire import digest
from managed_observation_http import build_observation_router
from managed_observations import Observations
from models import ApiKey, ManagedEnrollment, ManagedRuntime
from sqlalchemy import event
from sqlalchemy.orm import Session
from tests import test_managed_runtime_http as m
from tests.test_managed_runtime_http import http as http
from tests.test_managed_runtime_http import runtime_http as runtime_http
from tests.test_managed_issuance import specimen as specimen


def intent(h):
    return {
        "runtime_sha256": h.sha,
        "finished_at": "2026-11-02T18:00:01.123456789Z",
        "exit_code": 137,
        "observation_sha256": "4" * 64,
    }


def retire(h, body=None, headers=None):
    return m.post(
        h, "/observed-unbound-exit", intent(h) if body is None else body, headers
    )


@pytest.fixture
def observed_http(http):
    h = http
    h.app.include_router(build_observation_router(Observations(h.results)))
    return h


def observe(h, *, body=None, headers=None, include_runtime=True):
    values = {
        "origin": m.runtime.ORIGIN,
        "runner_id": m.RUNNER,
        "plan_sha256": digest(h.s["plan"]),
        "case_sha256": h.s["plan"]["case_hash"],
        "association_sha256": digest(
            {
                "origin": m.runtime.ORIGIN,
                "runner_id": m.RUNNER,
                "principal_sha256": hashlib.sha256(
                    ("Bearer " + m.KEY).encode()
                ).hexdigest(),
            }
        ),
    }
    if include_runtime:
        values.update(runtime_id=m.RUNTIME_ID, runtime_sha256=h.sha)
    return h.client.post(
        "/jobs/job-1/managed/observation",
        json=values if body is None else body,
        headers=h.headers if headers is None else headers,
    )


def test_retirement_preserves_unclaimed_job_and_permanently_fences_late_runtime_claim(
    http,
):
    h = http
    m.register(h)
    before = m.state(h)
    assert m.lookup(h).json() == {
        "schema": "vardr.worker-receipt-observation/1",
        "runtime_id": m.RUNTIME_ID,
        "runtime_sha256": h.sha,
        "binding": None,
        "receipt": None,
    }
    reply = retire(h)
    assert reply.status_code == 200, reply.text
    receipt = reply.json()["receipt"]
    payload = {
        "schema": "vardr.worker-unbound-retirement/1",
        "runtime_id": m.RUNTIME_ID,
        "runtime_sha256": h.sha,
        "origin": m.runtime.ORIGIN,
        "runner_id": m.RUNNER,
        "enrollment_id": "enrollment-1",
        "report_sha256": digest(
            {
                "schema": "vardr.worker-unbound-exit-report/1",
                "runtime_id": m.RUNTIME_ID,
                **intent(h),
            }
        ),
        "bound": False,
        "retired": True,
    }
    assert receipt == {**payload, "receipt_sha256": digest(payload)}
    assert m.state(h)[:-1] == before[:-1] == ("pending", 0, 0, 0, None, None, 0, 0)
    assert m.state(h)[-1] == (None, None, True, payload["report_sha256"])
    assert m.lookup(h).json()["receipt"] == receipt
    assert retire(h).json() == reply.json()
    assert retire(h, {**intent(h), "exit_code": 0}).status_code == 409
    h.s["wall"][0] += timedelta(seconds=1)
    assert m.register(h)["runtime_id"] == m.RUNTIME_ID  # No revival on exact replay.
    blocked = h.client.post(
        "/jobs/job-1/managed/claim",
        json={
            **h.body,
            "runtime_id": m.RUNTIME_ID,
            "runtime_sha256": h.sha,
        },
        headers=h.headers,
    )
    assert blocked.status_code == 409
    assert m.state(h)[:-1] == before[:-1]


def test_claim_winner_can_only_use_the_existing_exact_bound_exit_lane(http):
    h = http
    m.claim(h)
    before = m.state(h)
    assert retire(h).status_code == 409 and m.state(h) == before
    accepted = m.post(h, "/observed-exit", m.observed(h))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["receipt"]["cause"] == "observed_exit"
    assert m.lookup(h).json()["binding"] is not None


@pytest.mark.parametrize("change", ["expired", "revoked"])
def test_expired_or_revoked_grant_cannot_retire_but_can_read_an_existing_retirement(
    http, change
):
    h = http
    m.register(h)
    accepted = retire(h)
    assert accepted.status_code == 200
    before = m.state(h)
    if change == "expired":
        h.s["wall"][0] += timedelta(seconds=3601)
    else:
        assert m.post(h, "/revoke", {}, h.owner).status_code == 200
    assert retire(h).status_code == 409
    assert m.lookup(h).json()["receipt"] == accepted.json()["receipt"]
    assert m.state(h) == before


@pytest.mark.parametrize("change", ["expired", "revoked"])
def test_unbound_runtime_without_a_receipt_stays_held_after_grant_loss(http, change):
    h = http
    m.register(h)
    if change == "expired":
        h.s["wall"][0] += timedelta(seconds=3601)
    else:
        assert m.post(h, "/revoke", {}, h.owner).status_code == 200
    before = m.state(h)
    assert retire(h).status_code == 409 and m.state(h) == before
    assert m.lookup(h).json()["receipt"] is None


@pytest.mark.parametrize("headers", [None, "key", "owner", "foreign_stop"])
def test_reporting_authority_is_only_the_exact_independent_stop_capability(
    http, headers
):
    h = http
    m.register(h)
    selected = (
        {"Authorization": ""}
        if headers is None
        else {
            "key": h.headers,
            "owner": h.owner,
            "foreign_stop": {"Authorization": "VardrStop " + "f" * 64},
        }[headers]
    )
    before = m.state(h)
    assert retire(h, headers=selected).status_code == 404 and m.state(h) == before


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("runtime_sha256", "f" * 64, 409),
        ("finished_at", "2026-11-02T17:58:00Z", 409),
        ("exit_code", True, 422),
        ("token", "synthetic_do_not_echo", 422),
        ("outcome", "completed", 422),
    ],
)
def test_unbound_report_never_accepts_caller_selected_identity_or_execution_assertions(
    http, field, value, status
):
    h = http
    m.register(h)
    before = m.state(h)
    reply = retire(h, {**intent(h), field: value})
    assert reply.status_code == status and m.state(h) == before
    assert "synthetic_do_not_echo" not in reply.text


def test_failed_retirement_write_leaves_no_receipt_and_no_implicit_claim_denial(http):
    h = http
    m.register(h)
    before = m.state(h)

    def fault(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.startswith("UPDATE managed_runtimes")
            and "report_sha256" in statement
        ):
            raise RuntimeError("synthetic_do_not_echo")

    event.listen(h.s["engine"], "after_cursor_execute", fault)
    try:
        reply = retire(h)
    finally:
        event.remove(h.s["engine"], "after_cursor_execute", fault)
    assert reply.status_code == 503 and "synthetic_do_not_echo" not in reply.text
    assert m.state(h) == before and m.lookup(h).json()["receipt"] is None
    with Session(h.s["engine"]) as db:
        row = db.get(ManagedRuntime, m.RUNTIME_ID)
        assert row.retired is False and row.report_sha256 is None


@pytest.mark.parametrize("grant_loss", ["expired", "revoked"])
def test_original_key_observes_exact_unbound_retirement_without_changing_v1(
    observed_http,
    grant_loss,
):
    h = observed_http
    m.register(h)
    absence = observe(h)
    assert absence.status_code == 200 and absence.json()["runtime_retirement"] is None
    accepted = retire(h)
    assert accepted.status_code == 200
    before = m.state(h)
    v1 = observe(h, include_runtime=False)
    assert (
        v1.status_code == 200
        and v1.json()["schema"] == "vardr.managed-claim-observation/1"
    )
    assert "runtime_retirement" not in v1.json()
    observed = observe(h)
    assert observed.status_code == 200, observed.text
    assert observed.json() == {
        **v1.json(),
        "schema": "vardr.managed-claim-observation/2",
        "runtime_retirement": accepted.json()["receipt"],
    }
    assert (
        observed.json()["claim"] is None
        and observed.json()["capacity_reserved"] is False
    )
    if grant_loss == "expired":
        h.s["wall"][0] += timedelta(seconds=3601)
    else:
        assert m.post(h, "/revoke", {}, h.owner).status_code == 200
    assert observe(h).json() == observed.json() and m.state(h) == before


@pytest.mark.parametrize(
    "change",
    ["runtime_hash", "enrollment_revoke", "key_delete", "other_key", "owner_session"],
)
def test_retirement_observation_requires_original_enrolled_principal_and_runtime(
    observed_http, change
):
    h = observed_http
    m.register(h)
    assert retire(h).status_code == 200
    headers = h.headers
    if change == "runtime_hash":
        h.sha = "f" * 64
    elif change == "owner_session":
        headers = h.owner
    else:
        with Session(h.s["engine"]) as db:
            if change == "enrollment_revoke":
                db.get(ManagedEnrollment, "enrollment-1").revoked = True
            elif change == "key_delete":
                db.delete(db.get(ApiKey, "key-1"))
            else:
                raw = "vmap_" + "9" * 64
                db.add(
                    ApiKey(
                        id="key-2",
                        github_id="owner-1",
                        scope="runner",
                        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
                    )
                )
                headers = {"Authorization": "Bearer " + raw}
            db.commit()
    before = m.state(h)
    reply = observe(h, headers=headers)
    assert reply.status_code in {401, 403, 409} and m.state(h) == before
    assert "runtime_retirement" not in reply.json()


def test_runtime_observation_cannot_relabel_an_unrelated_native_claim(observed_http):
    h = observed_http
    m.register(h)
    accepted = h.client.post(
        "/jobs/job-1/managed/claim", json=h.body, headers=h.headers
    )
    assert accepted.status_code == 200
    assert retire(h).status_code == 200
    # The retirement is for that incarnation, never a claim-absence proof for
    # another attempt or permission to close a different run's metadata.
    assert observe(h).status_code == 409
    v1 = observe(h, include_runtime=False)
    assert v1.status_code == 200 and v1.json()["claim"] is not None


@pytest.mark.parametrize("missing", ["runtime_id", "runtime_sha256"])
def test_runtime_observation_pair_is_strictly_required(observed_http, missing):
    h = observed_http
    base = observe(h, include_runtime=False).json()
    body = {
        key: base[key]
        for key in (
            "origin",
            "runner_id",
            "plan_sha256",
            "case_sha256",
            "association_sha256",
        )
    }
    body.update(runtime_id=m.RUNTIME_ID, runtime_sha256=h.sha)
    del body[missing]
    assert observe(h, body=body).status_code == 422


@pytest.mark.parametrize(
    "values",
    [
        {"runtime_id": None},
        {"runtime_sha256": None},
        {"runtime_id": None, "runtime_sha256": None},
    ],
)
def test_supplied_null_runtime_fields_cannot_silently_fall_back_to_v1(
    observed_http, values
):
    h = observed_http
    base = observe(h, include_runtime=False).json()
    body = {
        key: base[key]
        for key in (
            "origin",
            "runner_id",
            "plan_sha256",
            "case_sha256",
            "association_sha256",
        )
    }
    assert observe(h, body={**body, **values}).status_code == 422
