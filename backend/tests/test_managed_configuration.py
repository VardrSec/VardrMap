"""Explicit service assembly; disposable keys and no database operations."""

import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
import pytest

from managed_configuration import ManagedConfigurationRefused, configure_managed
from managed_wire import b64


@pytest.fixture
def configuration(tmp_path):
    contract = tmp_path / "map.key"
    contract.write_bytes(bytes(range(32)))
    operator = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    trust = tmp_path / "operators.json"
    trust.write_text(
        json.dumps(
            [
                {
                    "issuer_id": "fixture-map",
                    "key_id": "fixture-operator",
                    "approver_id": "owner-1",
                    "public_key": b64(operator.public_key().public_bytes_raw()),
                    "revoked": False,
                }
            ]
        ),
        encoding="utf-8",
    )
    return {
        "VARDRMAP_MANAGED_WORKER": "1",
        "VARDRMAP_MANAGED_ORIGIN": "https://localhost:8443/backend",
        "VARDRMAP_MANAGED_ISSUER_ID": "fixture-map",
        "VARDRMAP_MANAGED_CONTRACT_KEY_ID": "fixture-contract",
        "VARDRMAP_MANAGED_OPERATOR_TRUST_FILE": str(trust),
        "VARDRMAP_MANAGED_CONTRACT_KEY_FILE": str(contract),
    }


@pytest.mark.parametrize("flag", [None, "0"])
def test_default_does_not_read_keys_construct_services_or_add_routes(monkeypatch, flag):
    import managed_configuration

    monkeypatch.setattr(
        managed_configuration,
        "_read",
        lambda *_: pytest.fail("key access while disabled"),
    )
    app = FastAPI()
    before = list(app.routes)
    assert (
        configure_managed(
            app, environ={} if flag is None else {"VARDRMAP_MANAGED_WORKER": flag}
        )
        is False
    )
    assert app.routes == before and not getattr(
        app.state, "managed_worker_enabled", False
    )


def test_enabled_assembly_exposes_shared_factories_without_database_or_scan(
    configuration, monkeypatch
):
    import managed_configuration
    import managed_http
    import managed_runtime_http
    import db

    calls = []
    control_factory = managed_http.build_managed_router
    runtime_factory = managed_runtime_http.build_runtime_router

    def controls(issuer, runtime):
        assert runtime.persistent_enabled is True
        calls.append((issuer, runtime))
        return control_factory(issuer, runtime)

    def runtimes(service):
        assert calls[0][1] is service and calls[0][0] is service.issuer
        return runtime_factory(service)

    monkeypatch.setattr(managed_http, "build_managed_router", controls)
    monkeypatch.setattr(managed_runtime_http, "build_runtime_router", runtimes)
    monkeypatch.setattr(
        db.engine,
        "connect",
        lambda *_: pytest.fail("database operation at configuration"),
    )
    app = FastAPI()
    assert managed_configuration.configure_managed(app, environ=configuration) is True
    paths = set(app.openapi()["paths"])
    assert "/jobs/managed/pending" in paths
    assert "/jobs/{job_id}/managed/claim" in paths
    assert "/jobs/{job_id}/managed/observation" in paths
    assert "/managed/runtimes/{runtime_id}/observed-exit" in paths
    assert app.state.managed_worker_enabled is True
    with pytest.raises(
        ManagedConfigurationRefused, match="^managed_worker_configuration_refused$"
    ):
        configure_managed(app, environ=configuration)


@pytest.mark.parametrize(
    "change",
    [
        {"VARDRMAP_MANAGED_WORKER": "true"},
        {"VARDRMAP_MANAGED_WORKER": ""},
        {"VARDRMAP_MANAGED_ORIGIN": "http://localhost:8443/backend"},
        {"VARDRMAP_MANAGED_ORIGIN": "https://localhost:8443/backend/"},
        {"VARDRMAP_MANAGED_ISSUER_ID": ""},
        {"VARDRMAP_MANAGED_CONTRACT_KEY_ID": "fixture-operator"},
        {"VARDRMAP_MANAGED_CONTRACT_KEY_FILE": "relative.key"},
    ],
)
def test_invalid_explicit_configuration_adds_no_routes_or_secret_details(
    configuration, change
):
    app = FastAPI()
    before = list(app.routes)
    with pytest.raises(
        ManagedConfigurationRefused, match="^managed_worker_configuration_refused$"
    ):
        configure_managed(app, environ={**configuration, **change})
    assert app.routes == before and not getattr(
        app.state, "managed_worker_enabled", False
    )


@pytest.mark.parametrize(
    "kind",
    [
        "key-size",
        "missing",
        "same-signing-key",
        "duplicate-trust",
        "unknown-trust-field",
        "revoked-type",
    ],
)
def test_key_and_public_trust_validation_never_provisions_or_repairs(
    configuration, kind
):
    key = Path(configuration["VARDRMAP_MANAGED_CONTRACT_KEY_FILE"])
    trust = Path(configuration["VARDRMAP_MANAGED_OPERATOR_TRUST_FILE"])
    anchors = json.loads(trust.read_text())
    if kind == "key-size":
        key.write_bytes(b"x" * 33)
    elif kind == "missing":
        key.unlink()
    elif kind == "same-signing-key":
        key.write_bytes(bytes(range(32, 64)))
    elif kind == "duplicate-trust":
        anchors.append(dict(anchors[0]))
    elif kind == "unknown-trust-field":
        anchors[0]["private_key"] = "public-invalid-fixture"
    else:
        anchors[0]["revoked"] = 0
    trust.write_text(json.dumps(anchors), encoding="utf-8")
    before = trust.read_bytes()
    app = FastAPI()
    routes = list(app.routes)
    with pytest.raises(
        ManagedConfigurationRefused, match="^managed_worker_configuration_refused$"
    ):
        configure_managed(app, environ=configuration)
    assert app.routes == routes and trust.read_bytes() == before
    if kind == "missing":
        assert not key.exists()


def test_actual_production_main_can_opt_in_without_database_bootstrap(
    configuration, tmp_path
):
    script = """
import sys
sys.path.insert(0, sys.argv[1])
import managed_runtime
original = managed_runtime.Runtimes
instances = []
def runtimes(results, *, persistent_enabled=False):
    service = original(results, persistent_enabled=persistent_enabled)
    instances.append(service)
    return service
managed_runtime.Runtimes = runtimes
from main import app
assert app.state.managed_worker_enabled is True
assert len(instances) == 1 and instances[0].persistent_enabled is True
assert '/managed/runtimes/{runtime_id}/observed-exit' in app.openapi()['paths']
print('managed_startup_configured')
"""
    database = "vardrmap_test_config_startup.db"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            script,
            str(Path(__file__).resolve().parents[1]),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            **configuration,
            "ENV": "production",
            "DATABASE_URL": "sqlite:///" + database,
            "VARDRMAP_AUTH_METHODS": "local",
            "SENTRY_DSN": "",
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "managed_startup_configured" in result.stdout
    assert not (tmp_path / database).exists()
