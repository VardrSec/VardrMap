"""Diagnostic redaction and exception identity, without a server or Runner."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests.exceptions import ReadTimeout

from tests.test_managed_tls import (
    WireFaults,
    bounded_transport,
    transport_failure_diagnostic,
)

ROUTE = "/jobs/job-1/managed/observation"
CANARY = "private-error-body-header-url-token-canary"


def test_diagnostic_reveals_only_fixed_class_category_and_status():
    error = RuntimeError(CANARY)
    error.__context__ = ReadTimeout(CANARY)
    fixture = SimpleNamespace(wire=SimpleNamespace(response_statuses={ROUTE: 503}))
    value = transport_failure_diagnostic(fixture, ROUTE, error)
    assert value == {
        "schema": "vardr.test-tls-diagnostic/1",
        "failure_kind": "ReadTimeout",
        "route_category": "observation",
        "http_status": 503,
    }
    unknown = type(
        CANARY, (Exception,), {"__str__": lambda self: pytest.fail("error text read")}
    )()
    value = transport_failure_diagnostic(fixture, "https://" + CANARY, unknown)
    assert value["failure_kind"] == value["route_category"] == "other"
    assert value["http_status"] is None
    assert CANARY not in json.dumps(value) and len(json.dumps(value)) < 512
    for status in (True, False, 99, 600, "200", None):
        fixture.wire.response_statuses[ROUTE] = status
        assert (
            transport_failure_diagnostic(fixture, ROUTE, error)["http_status"] is None
        )


def test_bounded_transport_reports_metadata_and_reraises_same_exception(capsys):
    error = RuntimeError(CANARY)
    error.__context__ = ReadTimeout(CANARY)

    def response_then_error(*args, **kwargs):
        fixture.wire.response_statuses[ROUTE] = 200
        raise error

    client = SimpleNamespace(managed_post=Mock(side_effect=response_then_error))
    fixture = SimpleNamespace(
        transport=lambda: SimpleNamespace(client=client, timeout=(1, 3)),
        wire=SimpleNamespace(response_statuses={ROUTE: 200}),
    )
    with pytest.raises(RuntimeError) as caught:
        bounded_transport(fixture).post(ROUTE, json={"token": CANARY})
    assert caught.value is error
    output = capsys.readouterr().out
    value = json.loads(output)
    assert set(value) == {"schema", "failure_kind", "route_category", "http_status"}
    assert value["failure_kind"] == "ReadTimeout" and value["http_status"] == 200
    assert CANARY not in output and len(output) < 512


def test_failed_request_cannot_reuse_a_previous_response_status(capsys):
    error = RuntimeError(CANARY)
    error.__context__ = ReadTimeout(CANARY)
    fixture = SimpleNamespace(
        transport=lambda: SimpleNamespace(
            client=SimpleNamespace(managed_post=Mock(side_effect=error)), timeout=(1, 3)
        ),
        wire=SimpleNamespace(response_statuses={ROUTE: 418}),
    )
    with pytest.raises(RuntimeError) as caught:
        bounded_transport(fixture).post(ROUTE, json={})
    assert caught.value is error
    assert json.loads(capsys.readouterr().out)["http_status"] is None


def test_wire_keeps_only_status_metadata():
    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [(b"private", CANARY.encode())],
            }
        )
        await send({"type": "http.response.body", "body": CANARY.encode()})

    async def discard(message):
        pass

    wire = WireFaults(app)
    asyncio.run(wire({"type": "http", "path": ROUTE}, None, discard))
    assert wire.response_statuses == {ROUTE: 503}
    diagnostic = transport_failure_diagnostic(
        SimpleNamespace(wire=wire), ROUTE, RuntimeError(CANARY)
    )
    assert CANARY not in json.dumps(diagnostic)
