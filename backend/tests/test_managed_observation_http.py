"""Explicit read-only router factory; synthetic enrollment and disposable SQL only."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.requests import Request

import managed_observation_http as boundary
from db import get_db
from models import (
    ApiKey,
    Engagement,
    JobExecution,
    ManagedApproval,
    ManagedContract,
    ManagedEnrollment,
    ScanJob,
)
from tests.test_managed_issuance import KEY, claim, mint_token
from tests.test_managed_issuance import specimen as specimen
from tests.test_managed_observations import observation as observation
from tests.test_managed_observations import (
    test_owned_terminal_receipts_can_be_observed_without_original_capability as terminal_setup,
)

PATH = "/jobs/job-1/managed/observation"


@pytest.fixture
def http(observation):
    s, service, args = observation
    app = FastAPI()
    app.include_router(boundary.build_observation_router(service))

    def database():
        with Session(s["engine"]) as db:
            yield db

    app.dependency_overrides[get_db] = database
    body = {k: args[k] for k in ("plan_sha256", "case_sha256", "association_sha256")}
    body.update(origin=args["body"].origin, runner_id=str(args["body"].runner_id))
    with TestClient(app, base_url="https://map.synthetic.test") as client:
        yield SimpleNamespace(
            s=s,
            service=service,
            body=body,
            app=app,
            client=client,
            headers={"Authorization": "Bearer " + KEY},
            observation=observation,
        )


def business(s):
    with Session(s["engine"]) as db:
        e, j = db.get(Engagement, "eng-1"), db.get(ScanJob, "job-1")
        x = db.get(JobExecution, "job-1")
        return (
            e.targets_spent,
            e.duration_allocated,
            j.status,
            db.query(ManagedApproval).one().issued,
            db.query(ManagedContract).count(),
            (x.state, x.capacity_reserved, x.expires_at) if x else None,
        )


def test_absent_then_claim_observation_never_creates_or_renews_permission(http):
    h = http
    before = business(h.s)
    reply = h.client.post(PATH, json=h.body, headers=h.headers)
    assert reply.status_code == 200 and reply.json()["claim"] is None
    assert reply.headers["Cache-Control"] == "no-store" and business(h.s) == before
    claim(h.s)
    before = business(h.s)
    reply = h.client.post(PATH, json=h.body, headers=h.headers)
    assert reply.status_code == 200 and reply.json()["claim"]["consumed"] is False
    assert business(h.s) == before
    assert all(
        value not in reply.text for value in ('"token"', '"envelope"', '"lease_seconds"', KEY)
    )


@pytest.mark.parametrize("kind", ["result", "stop"])
def test_retained_terminal_receipt_http_is_read_only_and_no_capability(http, kind):
    h = http
    terminal_setup(h.observation, kind)
    before = business(h.s)
    reply = h.client.post(PATH, json=h.body, headers=h.headers)
    assert reply.status_code == 200
    data = reply.json()
    assert data["claim"]["consumed"] and data["capacity_reserved"] is False
    assert data["completion" if kind == "result" else "stop"] is not None
    assert business(h.s) == before


@pytest.mark.parametrize(
    "kind,status",
    [
        ("missing", 401),
        ("invalid", 401),
        ("jwt", 403),
        ("foreign", 404),
        ("revoked_enrollment", 409),
        ("deleted_key", 401),
    ],
)
def test_authentication_never_substitutes_owner_uuid_for_enrollment(http, kind, status):
    h = http
    headers = dict(h.headers)
    if kind == "missing":
        headers = {}
    elif kind == "invalid":
        headers = {"Authorization": "Bearer vmap_invalid_synthetic"}
    elif kind in {"jwt", "foreign"}:
        headers = {"Authorization": "Bearer " + mint_token("owner-1" if kind == "jwt" else "other")}
    else:
        with Session(h.s["engine"]) as db:
            if kind == "revoked_enrollment":
                db.get(ManagedEnrollment, "enrollment-1").revoked = True
            else:
                db.delete(
                    db.query(ApiKey)
                    .filter_by(key_hash=h.s["db"].query(ApiKey).one().key_hash)
                    .one()
                )
            db.commit()
    before = business(h.s)
    reply = h.client.post(PATH, json=h.body, headers=headers)
    assert reply.status_code == status
    assert reply.json() == {"detail": "managed_observation_refused"}
    assert reply.headers["Cache-Control"] == "no-store" and business(h.s) == before


@pytest.mark.parametrize(
    "change,status",
    [
        ("token", 422),
        ("extra_budget", 422),
        ("bad_uuid", 422),
        ("bad_hash", 422),
        ("origin_type", 422),
        ("foreign_hash", 409),
        ("wrong_runner", 409),
    ],
)
def test_exact_bound_input_refuses_secret_or_identity_changes_without_echo(http, change, status):
    h = http
    body = dict(h.body)
    if change == "token":
        body["token"] = "synthetic_do_not_echo"
    elif change == "extra_budget":
        body["concurrency_budget"] = True
    elif change == "bad_uuid":
        body["runner_id"] = "synthetic_do_not_echo"
    elif change == "bad_hash":
        body["plan_sha256"] = True
    elif change == "origin_type":
        body["origin"] = 1
    elif change == "foreign_hash":
        body["association_sha256"] = "0" * 64
    else:
        body["runner_id"] = "00000000-0000-0000-0000-000000000099"
    before = business(h.s)
    reply = h.client.post(PATH, json=body, headers=h.headers)
    assert reply.status_code == status and "synthetic_do_not_echo" not in reply.text
    assert reply.headers["Cache-Control"] == "no-store" and business(h.s) == before


@pytest.mark.parametrize(
    "kind,status",
    [
        ("duplicate", 422),
        ("invalid_utf8", 422),
        ("overflow", 422),
        ("length", 413),
        ("stream", 413),
        ("encoding", 415),
        ("media_type", 415),
        ("empty", 422),
    ],
)
def test_body_byte_media_and_strict_json_boundaries(http, kind, status):
    h = http
    headers = {**h.headers, "Content-Type": "application/json"}
    data = b"{}"
    if kind == "duplicate":
        data = b'{"token":"synthetic_do_not_echo","token":1}'
    elif kind == "invalid_utf8":
        data = b"\xff"
    elif kind == "overflow":
        data = b'{"x":1e999}'
    elif kind == "length":
        headers["Content-Length"] = "9000"
    elif kind == "stream":
        data = iter([b"x" * 8192, b"x"])
    elif kind == "encoding":
        headers["Content-Encoding"] = "gzip"
    elif kind == "media_type":
        headers["Content-Type"] = "text/plain"
    else:
        data = b""
    before = business(h.s)
    reply = h.client.post(PATH, content=data, headers=headers)
    assert reply.status_code == status and reply.json() == {"detail": "managed_observation_refused"}
    assert "synthetic_do_not_echo" not in reply.text and business(h.s) == before


def test_router_does_not_activate_in_main_or_offer_permission_mutations(http):
    from main import app

    assert boundary.OBSERVATION_PATH not in app.openapi()["paths"]
    paths = http.app.openapi()["paths"]
    assert list(paths) == [boundary.OBSERVATION_PATH]
    assert set(paths[boundary.OBSERVATION_PATH]) == {"post"}
    assert (
        http.client.post(
            PATH.replace("job-1", "foreign"), json=http.body, headers=http.headers
        ).status_code
        == 404
    )
    assert (
        http.client.post(
            PATH.replace("job-1", "bad.job"), json=http.body, headers=http.headers
        ).status_code
        == 422
    )
    assert (
        http.client.post(
            "http://map.synthetic.test" + PATH, json=http.body, headers=http.headers
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "kind,status",
    [("timeout", 408), ("disconnect", 400), ("failure", 503), ("oversized_reply", 503)],
)
def test_bounded_body_wait_and_service_failures_never_expose_details(
    http, monkeypatch, kind, status
):
    service = Mock()
    if kind == "failure":
        service.inspect.side_effect = OSError("synthetic_do_not_echo")
    elif kind == "oversized_reply":
        service.inspect.return_value = {"x": "a" * 16385}
    router = boundary.build_observation_router(service)
    monkeypatch.setattr(boundary, "BODY_TIMEOUT_SECONDS", 0.01)
    raw = json.dumps(http.body).encode()

    async def receive():
        if kind == "timeout":
            await asyncio.sleep(1)
        if kind == "disconnect":
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": raw, "more_body": False}

    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("map.synthetic.test", 443),
            "path": PATH,
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    reply = asyncio.run(router.routes[0].endpoint("job-1", request, db=None))
    assert reply.status_code == status and "synthetic_do_not_echo" not in reply.body.decode()
    assert reply.headers["Cache-Control"] == "no-store"
    if kind in {"timeout", "disconnect"}:
        service.inspect.assert_not_called()
