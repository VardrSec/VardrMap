"""Explicit loopback TLS fixture; no installed service, Gate or target dispatch."""

import asyncio
import copy
import importlib.util
import os
import socket
import ssl
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from models import Engagement, JobExecution, ManagedApproval, ManagedContract
from sqlalchemy.orm import Session
from tests.test_managed_http import PASSWORD
from tests.test_managed_http import harness as harness
from tests.test_managed_issuance import KEY, NOW, signed
from tests.test_managed_issuance import specimen as specimen

pytestmark = pytest.mark.skipif(
    os.environ.get("NM2_TLS_LOOPBACK") != "1" or not os.environ.get("NM2_RUNNER_SOURCE"),
    reason="explicit isolated two-repository loopback TLS fixture only",
)


@pytest.fixture
def tls_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    yield sock
    sock.close()


@pytest.fixture
def map_origin(tls_socket, request):
    return f"https://localhost:{tls_socket.getsockname()[1]}" + getattr(request, "param", "")


class ConfiguredPrefix:
    """Synthetic equivalent of the existing Caddy /backend handle_path."""

    def __init__(self, app, prefix):
        self.app, self.prefix = app, prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.prefix:
            if not scope["path"].startswith(self.prefix + "/"):
                await send({"type": "http.response.start", "status": 404, "headers": []})
                return await send({"type": "http.response.body", "body": b""})
            scope = dict(scope)
            scope["path"] = scope["path"][len(self.prefix):]
            scope["raw_path"] = scope["path"].encode()
        return await self.app(scope, receive, send)


def certificates(directory, kind="valid"):
    """Real short-lived named leaf under a disposable CA; never machine trust."""
    instant = datetime.now(timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NM2 disposable CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(instant - timedelta(days=2))
        .not_valid_after(instant + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    host = "wrong.synthetic.test" if kind == "wrong_name" else "localhost"
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(instant - timedelta(days=1))
        .not_valid_after(
            instant - timedelta(hours=1) if kind == "expired" else instant + timedelta(minutes=30)
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    directory.mkdir()
    ca_path, cert_path, key_path = (
        directory / name for name in ("ca.pem", "server.pem", "server-key.pem")
    )
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return ca_path, cert_path, key_path


class WireFaults:
    """Wire-only faults around actual auth/issuance/control; no policy overrides."""

    def __init__(self, app):
        self.app, self.mode, self.location = app, "normal", ""
        self.seen, self.forwarded = {}, {}
        self.cached = []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        self.seen[path] = self.seen.get(path, 0) + 1
        if self.mode == "managed_raw" and path == "/fixture/claim":
            await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
            return await send({"type": "http.response.body", "body": self.raw_body})
        if path in {
            "/fixture/claim",
            "/fixture/current",
            "/fixture/review",
        } and self.mode.startswith("redirect"):
            await send(
                {
                    "type": "http.response.start",
                    "status": int(self.mode.split("_")[1]),
                    "headers": [(b"location", self.location.encode()), (b"content-length", b"2")],
                }
            )
            return await send({"type": "http.response.body", "body": b"{}"})
        if self.mode == "status500" and path == "/fixture/claim":
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-length", b"2")],
                }
            )
            return await send({"type": "http.response.body", "body": b"{}"})
        if self.mode == "replay_current" and path == "/fixture/current":
            for message in self.cached:
                await send(copy.deepcopy(message))
            return
        self.forwarded[path] = self.forwarded.get(path, 0) + 1

        async def outgoing(message):
            if self.mode == "capture_current" and path == "/fixture/current":
                self.cached.append(copy.deepcopy(message))
            if (
                self.mode == "slow_current"
                and path == "/fixture/current"
                and message["type"] == "http.response.start"
            ):
                await asyncio.sleep(0.5)  # Real network read timeout after actual DB commit.
            if (
                self.mode == "drop_" + path.rsplit("/", 1)[-1]
                and message["type"] == "http.response.start"
            ):
                message = copy.deepcopy(message)
                message["headers"] = [
                    (k, str(int(v) + 17).encode() if k == b"content-length" else v)
                    for k, v in message["headers"]
                ]
                # The intentionally truncated response closes the real TLS socket.
            await send(message)

        await self.app(scope, receive, outgoing)


@pytest.fixture
def tls_harness(harness, tls_socket, tmp_path):
    h = harness
    source = Path(os.environ["NM2_RUNNER_SOURCE"])
    spec = importlib.util.spec_from_file_location(
        "nm2_tls_transport", source / "tests" / "managed_tls_transport.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ca, cert, key = certificates(tmp_path / "tls")
    wire = WireFaults(h.app)
    clients = []

    @contextmanager
    def serve(sock=tls_socket, cert_file=cert, key_file=key):
        server = uvicorn.Server(
            uvicorn.Config(
                ConfiguredPrefix(wire, urlsplit(h.origin).path),
                log_config=None,
                access_log=False,
                log_level="critical",
                lifespan="off",
                ssl_certfile=str(cert_file),
                ssl_keyfile=str(key_file),
                timeout_keep_alive=1,
                timeout_graceful_shutdown=1,
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started and thread.is_alive(), "disposable TLS server did not start"
        try:
            yield server
        finally:
            for client in clients:
                client.close()
            server.should_exit = True
            thread.join(5)
            assert not thread.is_alive(), "disposable TLS server did not stop"

    def transport(token=KEY, ca_file=ca, origin=h.origin):
        value = module.FixtureTransport(origin, token, ca_file)
        clients.append(value)
        return value

    def issue(auth="jwt"):
        if auth == "local":
            operator = transport(token="")
            operator.client.session.headers["Origin"] = h.origin
            operator.client.post(
                "/auth/local/login", json={"username": "operator", "password": PASSWORD}
            )
            session = operator.client.get("/auth/local/session")
            operator.client.session.headers["X-CSRF-Token"] = session["csrfToken"]
        else:
            operator = transport(token=h.owner["Authorization"].split(" ", 1)[1])
        reviewed = operator.client.post("/fixture/review", json=h.review)
        receipt = signed(reviewed["context"])
        operator.client.post(
            "/fixture/register",
            json={
                **{k: h.review[k] for k in ("job_id", "enrollment_id", "authorization_id", "plan")},
                "approval": receipt,
            },
        )
        return operator

    try:
        yield SimpleNamespace(
            h=h, ca=ca, cert=cert, key=key, wire=wire, serve=serve, transport=transport, issue=issue
        )
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize("auth", ["jwt", "local"])
def test_verified_https_auth_to_inert_launch(tls_harness, auth):
    t, launched = tls_harness, []
    with t.serve():
        t.issue(auth)
        transport = t.transport()
        assert transport.client.session.verify == str(t.ca)
        assert transport.client.session.max_redirects == 0
        assert transport.client.session.get_adapter(t.h.origin).max_retries.total == 0
        p = t.h.probe(transport)
        p.claim(t.h.body)
        p.reserve()
        p.launch(lambda: launched.append(True))
    assert launched == [True]
    assert t.wire.forwarded["/fixture/claim"] == 1
    with Session(t.h.s["engine"]) as db:
        assert db.query(ManagedApproval).one().issued == 1
        assert db.query(ManagedContract).one().consumed is False


def exception_chain(error):
    pending, found, seen = [error], [], set()
    while pending:
        value = pending.pop()
        if not isinstance(value, BaseException) or id(value) in seen:
            continue
        seen.add(id(value))
        found.append(value)
        pending.extend(
            [value.__cause__, value.__context__, getattr(value, "reason", None), *value.args]
        )
    return found


@pytest.mark.parametrize("kind", ["untrusted", "wrong_name", "expired"])
def test_certificate_failures_precede_authenticated_http(tls_harness, tmp_path, kind):
    from requests.exceptions import SSLError

    t = tls_harness
    if kind == "untrusted":
        ca, _, _ = certificates(tmp_path / "unrelated-ca")
        server = t.serve()
    else:
        ca, cert, key = certificates(tmp_path / "bad-cert", kind)
        server = t.serve(cert_file=cert, key_file=key)
    with server, pytest.raises(SSLError) as denied:
        t.transport(ca_file=ca).client.post("/fixture/claim", json=t.h.body)
    codes = {
        error.verify_code
        for error in exception_chain(denied.value)
        if isinstance(error, ssl.SSLCertVerificationError)
    }
    assert codes & {"untrusted": {20, 21}, "wrong_name": {62}, "expired": {10}}[kind]
    assert t.wire.seen == {}
    assert t.h.s["db"].query(ManagedContract).count() == 0


@pytest.fixture
def http_sink():
    class Sink(BaseHTTPRequestHandler):
        def do_POST(self):
            self.server.contacts += 1
            self.server.credential_seen |= bool(
                self.headers.get("Authorization") or self.headers.get("Cookie")
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        do_GET = do_POST

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Sink)
    server.contacts, server.credential_seen = 0, False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("destination", ["http", "same_https"])
@pytest.mark.parametrize("credential", ["api_key", "cookie"])
def test_redirects_are_refused_before_credential_forwarding(
    tls_harness, http_sink, code, destination, credential
):
    from requests.exceptions import TooManyRedirects

    t = tls_harness
    with t.serve():
        operator = t.issue("local" if credential == "cookie" else "jwt")
        t.wire.mode = f"redirect_{code}"
        t.wire.location = (
            f"http://127.0.0.1:{http_sink.server_port}/sink"
            if destination == "http"
            else t.h.origin + "/fixture/sink"
        )
        client = operator if credential == "cookie" else t.transport()
        path = "/fixture/review" if credential == "cookie" else "/fixture/claim"
        body = t.h.review if credential == "cookie" else t.h.body
        before = t.wire.seen.get(path, 0)
        with pytest.raises(TooManyRedirects):
            client.client.post(path, json=body)
        assert t.wire.seen[path] == before + 1
        assert "/fixture/sink" not in t.wire.seen
    assert http_sink.contacts == 0 and not http_sink.credential_seen
    assert t.h.s["db"].query(ManagedContract).count() == 0


@pytest.mark.parametrize("kind", ["status500", "drop_claim"])
def test_nonidempotent_claim_is_not_retried(tls_harness, kind):
    t = tls_harness
    with t.serve():
        t.issue()
        t.wire.mode = kind
        transport = t.transport()
        p = t.h.probe(transport)
        with pytest.raises(t.h.error, match="synthetic_transport_failed"):
            p.claim(t.h.body)
        with pytest.raises(t.h.error, match="single_claim_only"):
            p.claim(t.h.body)
        assert t.wire.seen["/fixture/claim"] == 1
        assert transport.failure_kind == (
            "HTTPError" if kind == "status500" else "ChunkedEncodingError"
        )
    with Session(t.h.s["engine"]) as db:
        assert db.query(ManagedContract).count() == (1 if kind == "drop_claim" else 0)
        if kind == "drop_claim":
            assert db.get(JobExecution, "job-1").capacity_reserved
            assert db.get(Engagement, "eng-1").duration_allocated == 30


@pytest.mark.parametrize("kind", ["drop_current", "slow_current"])
def test_ambiguous_control_cannot_extend_local_permission(tls_harness, kind):
    t = tls_harness
    with t.serve():
        t.issue()
        transport = t.transport()
        p = t.h.probe(transport)
        p.claim(t.h.body)
        p.reserve()
        t.h.ticks[0] = 2
        t.wire.mode = kind
        transport.timeout = (1, 0.1)
        with pytest.raises(t.h.error, match="synthetic_transport_failed"):
            p.launch(lambda: pytest.fail("inert sentinel reached after ambiguous HTTPS control"))
        assert t.wire.seen["/fixture/current"] == 2
        assert transport.failure_kind == (
            "ReadTimeout" if kind == "slow_current" else "ChunkedEncodingError"
        )
        assert p.lease_end == 10
    with Session(t.h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == (NOW + timedelta(seconds=12)).replace(
            tzinfo=None
        )
        assert db.get(JobExecution, "job-1").capacity_reserved


@pytest.mark.parametrize("rollback", [False, True])
def test_cached_https_reply_keeps_actual_fixed_expiry(tls_harness, rollback):
    t = tls_harness
    with t.serve():
        t.issue()
        t.wire.mode = "capture_current"
        p = t.h.probe(t.transport())
        p.claim(t.h.body)
        p.reserve()
        t.wire.mode = "replay_current"
        t.h.ticks[0] = 8
        if rollback:
            t.h.wall[0] = NOW - timedelta(hours=1)
        p.revalidate()
        assert p.lease_end == 10
        t.h.ticks[0] = 11
        with pytest.raises(t.h.error, match="permission_expired"):
            p.launch(lambda: pytest.fail("TLS replay revived server-expired permission"))
        assert t.wire.forwarded["/fixture/current"] == 1


def test_connection_refusal_prevents_claim_without_fallback(harness, tmp_path):
    from requests.exceptions import ConnectionError, SSLError

    source = Path(os.environ["NM2_RUNNER_SOURCE"])
    spec = importlib.util.spec_from_file_location(
        "nm2_refused_transport", source / "tests" / "managed_tls_transport.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ca, _, _ = certificates(tmp_path / "refused-ca")
    failures = []

    class Observed(module.FixtureTransport):
        def post(self, path, *, json):
            try:
                return super().post(path, json=json)
            except ConnectionError as error:
                failures.append(error)
                raise

    # Retain exclusive ownership without listening, so no other process can
    # take the port and turn refusal into a different server's response.
    with socket.socket() as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", 0))
        transport = Observed(
            f"https://localhost:{sock.getsockname()[1]}", KEY, ca, timeout=(3, 0.2)
        )
        try:
            p = harness.probe(transport)
            with pytest.raises(harness.error, match="synthetic_transport_failed"):
                p.claim(harness.body)
            assert len(failures) == 1 and not isinstance(failures[0], SSLError)
            assert any(
                isinstance(error, ConnectionRefusedError) for error in exception_chain(failures[0])
            ), [type(error).__name__ for error in exception_chain(failures[0])]
            assert harness.s["db"].query(ManagedContract).count() == 0
        finally:
            transport.close()


@pytest.mark.parametrize("lost", [False, True])
def test_verified_https_consumption_ack_and_postcommit_loss(tls_harness, lost):
    """Bound ACK over verified sockets; no process/target execution."""
    from vardrrunner.authorization.claim import ClaimError, ManagedRun
    from vardrrunner.authorization.codec import digest, encoded

    t, states = tls_harness, []
    with t.serve():
        t.issue()
        transport = t.transport()
        probe = t.h.probe(transport)
        probe.claim(t.h.body)
        probe.reserve()
        if lost:
            t.wire.mode = "drop_consume"
        binding = {
            **probe.binding,
            **{k: probe.payload[k] for k in ("contract_id", "attempt_id", "fence")},
            "authority_revision": probe.context.authority_revision,
            "authority_sha256": probe.context.authority_sha256,
        }

        def record(run_id, owner, *, acknowledged):
            states.append(acknowledged)

        handle = ManagedRun(
            SimpleNamespace(binding=binding, envelope=probe.envelope),
            SimpleNamespace(consumption=record),
            "inert-run",
            "inert-owner",
            1000000,
            lambda body: transport.client.post("/fixture/consume", json=body),
        )
        body = {**probe.request, "contract_sha256": digest(encoded(probe.envelope))}
        if lost:
            with pytest.raises(ClaimError, match="consumption_outcome_unknown"):
                handle._acknowledge(body)
        else:
            handle._acknowledge(body)
        assert states == ([False] if lost else [False, True])
        assert t.wire.forwarded["/fixture/consume"] == 1
        with Session(t.h.s["engine"]) as db:
            assert db.query(ManagedContract).one().consumed
            assert db.get(JobExecution, "job-1").capacity_reserved


@pytest.mark.parametrize("lost", [None, "result", "finish"])
def test_verified_https_results_completion_and_lost_replies(tls_harness, lost):
    from tests.managed_result_probe import flow

    t = tls_harness
    with t.serve():
        t.issue()
        flow(t.h, t.transport(), wire=t.wire, lost=lost)
    assert t.wire.forwarded["/fixture/result"] == 1
    assert t.wire.forwarded.get("/fixture/finish", 0) == (0 if lost == "result" else 1)


@pytest.mark.parametrize("lost", [False, True])
def test_verified_https_owned_stop_receipt_and_postcommit_loss(tls_harness, lost):
    from tests.managed_stop_probe import flow

    t = tls_harness
    with t.serve():
        t.issue()
        flow(t.h, t.transport(), wire=t.wire, lost=lost)
    assert t.wire.forwarded["/fixture/stopped"] == 1


@pytest.mark.parametrize("kind", ["result", "stop"])
def test_verified_https_capability_free_claim_observation(tls_harness, kind):
    from tests.managed_observation_probe import flow

    t = tls_harness
    with t.serve():
        t.issue()
        flow(t.h, t.transport(), kind=kind)
    assert t.wire.forwarded["/fixture/observe"] == 2


def bounded_transport(t):
    """Test-only adapter to Runner's explicit production-code HTTP primitive."""
    transport = t.transport()

    def post(path, *, json):
        payload = transport.client.managed_post(path, json, timeout=transport.timeout)
        return SimpleNamespace(status_code=200, json=lambda: payload)

    return SimpleNamespace(post=post, client=transport.client)


@pytest.mark.parametrize("kind", ["result", "stop"])
def test_explicit_managed_transport_full_receipt_flow(tls_harness, kind):
    from tests.managed_observation_probe import flow

    t = tls_harness
    with t.serve():
        t.issue()
        flow(t.h, bounded_transport(t), kind=kind)
    assert t.wire.forwarded["/fixture/claim"] == 1
    assert t.wire.forwarded["/fixture/observe"] == 2


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_explicit_managed_transport_never_follows_redirect(tls_harness, http_sink, code):
    from vardrrunner.api import ManagedTransportError

    t = tls_harness
    with t.serve():
        t.issue()
        t.wire.mode, t.wire.location = f"redirect_{code}", f"http://127.0.0.1:{http_sink.server_port}/sink"
        with pytest.raises(ManagedTransportError, match="^managed request failed$"):
            bounded_transport(t).post("/fixture/claim", json=t.h.body)
        assert t.wire.seen["/fixture/claim"] == 1
    assert http_sink.contacts == 0 and not http_sink.credential_seen


@pytest.mark.parametrize("kind", ["status500", "drop_claim"])
def test_explicit_managed_transport_does_not_replay_ambiguous_claim(tls_harness, kind):
    from vardrrunner.api import ManagedTransportError

    t = tls_harness
    with t.serve():
        t.issue()
        t.wire.mode = kind
        with pytest.raises(ManagedTransportError):
            bounded_transport(t).post("/fixture/claim", json=t.h.body)
        assert t.wire.seen["/fixture/claim"] == 1
    with Session(t.h.s["engine"]) as db:
        assert db.query(ManagedContract).count() == (1 if kind == "drop_claim" else 0)
        if kind == "drop_claim":
            assert db.get(JobExecution, "job-1").capacity_reserved


@pytest.mark.parametrize("kind", ["declared_size", "chunked_size", "duplicate", "overflow", "utf8", "encoding", "content_type"])
def test_explicit_managed_transport_bounds_real_response(tls_harness, kind):
    from vardrrunner.api import ManagedTransportError

    t = tls_harness
    body = {"duplicate": b'{"x":1,"x":2}', "overflow": b'{"x":1e999}', "utf8": b'\xff'}.get(kind, b"x" * 262145)
    headers = [(b"content-type", b"application/json")]
    if kind == "declared_size":
        headers.append((b"content-length", str(len(body)).encode()))
    elif kind == "encoding":
        headers.append((b"content-encoding", b"gzip"))
    elif kind == "content_type":
        headers = [(b"content-type", b"text/html")]
    with t.serve():
        t.issue()
        t.wire.mode, t.wire.raw_body, t.wire.raw_headers = "managed_raw", body, headers
        with pytest.raises(ManagedTransportError, match="^managed request failed$"):
            bounded_transport(t).post("/fixture/claim", json=t.h.body)
        assert t.wire.seen["/fixture/claim"] == 1
    assert t.h.s["db"].query(ManagedContract).count() == 0


def test_explicit_managed_transport_requires_actual_trusted_ca(tls_harness, tmp_path):
    from vardrrunner.api import ManagedTransportError

    t = tls_harness
    wrong_ca, _, _ = certificates(tmp_path / "untrusted-managed")
    with t.serve():
        client = t.transport(ca_file=wrong_ca).client
        with pytest.raises(ManagedTransportError):
            client.managed_post("/fixture/claim", t.h.body)
    assert not t.wire.seen


@pytest.mark.parametrize("kind", ["result", "stop"])
def test_unregistered_observation_router_over_verified_managed_transport(tls_harness, kind):
    from tests.managed_observation_probe import flow

    t = tls_harness
    with t.serve():
        t.issue()
        transport = bounded_transport(t)

        def post(path, *, json):
            if path == "/fixture/observe":
                path = "/jobs/job-1/managed/observation"
            return transport.post(path, json=json)

        flow(t.h, SimpleNamespace(post=post), kind=kind)
    assert t.wire.forwarded["/jobs/job-1/managed/observation"] == 2
    assert "/fixture/observe" not in t.wire.seen


@pytest.mark.parametrize("map_origin", ["/backend"], indirect=True)
@pytest.mark.parametrize("kind", ["result", "stop"])
def test_existing_full_api_prefix_preserves_signed_origin_and_receipts(tls_harness, kind):
    from tests.managed_observation_probe import flow

    t = tls_harness
    assert t.h.origin.endswith("/backend")
    with t.serve():
        t.issue()
        transport = bounded_transport(t)
        assert transport.client.base == t.h.origin

        def post(path, *, json):
            if path == "/fixture/observe":
                path = "/jobs/job-1/managed/observation"
            return transport.post(path, json=json)

        flow(t.h, SimpleNamespace(post=post), kind=kind)
    assert t.wire.forwarded["/jobs/job-1/managed/observation"] == 2
    assert t.wire.forwarded["/fixture/claim"] == 1
