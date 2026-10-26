"""Readiness is a read-only migration marker check, separate from liveness/auth."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
import readiness
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError


@pytest.fixture
def probe(tmp_path):
    database = create_engine("sqlite:///" + str(tmp_path / "readiness.db"))
    yield database
    database.dispose()


@pytest.mark.parametrize(
    "revisions", [[], ["older"], ["future"], ["expected", "other"]]
)
def test_missing_or_different_marker_is_not_ready(probe, monkeypatch, revisions):
    monkeypatch.setattr(readiness, "expected_heads", lambda: ("expected",))
    with probe.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(64))")
        )
        for revision in revisions:
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
    result = readiness.snapshot(probe)
    assert result["status"] == "not_ready"
    assert result["checks"] == {"database": "ok", "migrations": "not_current"}
    with probe.connect() as connection:
        assert (
            list(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars()
            )
            == revisions
        )


def test_empty_database_does_not_get_stamped_or_migrated(probe, monkeypatch):
    monkeypatch.setattr(readiness, "expected_heads", lambda: ("expected",))
    assert readiness.snapshot(probe)["checks"]["migrations"] == "not_current"
    with probe.connect() as connection:
        assert (
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).all()
            == []
        )


def test_current_marker_is_ready_without_changing_it(probe, monkeypatch):
    expected = readiness.expected_heads()
    assert len(expected) == 1
    with probe.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(64))")
        )
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": expected[0]},
        )
    result = readiness.snapshot(probe)
    assert result["schema_version"] == 1 and result["component"] == "vardrmap-api"
    assert result["status"] == "ready"
    assert datetime.fromisoformat(result["checked_at"]).tzinfo is not None


@pytest.mark.parametrize("expected", [(), ("first", "second")])
def test_invalid_migration_package_is_unavailable(probe, monkeypatch, expected):
    monkeypatch.setattr(readiness, "expected_heads", lambda: expected)
    assert readiness.snapshot(probe)["checks"]["migrations"] == "unavailable"


def test_metadata_failure_is_value_free(probe, monkeypatch):
    def failed():
        raise RuntimeError("private/path DSN-password fixture-secret")

    monkeypatch.setattr(readiness, "expected_heads", failed)
    result = readiness.snapshot(probe)
    assert result["checks"] == {"database": "ok", "migrations": "unavailable"}
    assert "private" not in str(result) and "fixture-secret" not in str(result)


def test_database_failure_is_not_a_healthy_schema():
    probe = MagicMock()
    probe.connect.side_effect = OperationalError(
        "private-host secret", {}, Exception("password")
    )
    result = readiness.snapshot(probe)
    assert result["status"] == "not_ready"
    assert result["checks"] == {"database": "unavailable", "migrations": "not_checked"}
    assert "secret" not in str(result) and "password" not in str(result)


def test_postgres_probe_preserves_tls_and_bounds_reads(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(readiness, "create_engine", factory)
    readiness.probe_engine.cache_clear()
    url = make_url(
        "postgresql+psycopg://reader:private@localhost/readiness?sslmode=verify-full"
    )
    readiness.probe_engine(url)
    args = factory.call_args.kwargs["connect_args"]
    assert factory.call_args.args[0] is url
    assert args["sslmode"] == "verify-full" and args["connect_timeout"] == 3
    assert "statement_timeout=3000" in args["options"]
    assert "default_transaction_read_only=on" in args["options"]
    readiness.probe_engine.cache_clear()


@pytest.mark.parametrize("ready,code", [(True, 200), (False, 503)])
def test_public_readiness_has_no_cache_and_does_not_bypass_auth(
    client, monkeypatch, ready, code
):
    probe = MagicMock()
    probe.connect.side_effect = OperationalError("secret", {}, Exception("private"))
    result = readiness.snapshot(probe)
    if ready:
        result.update(
            status="ready", checks={"database": "ok", "migrations": "current"}
        )
    monkeypatch.setattr(readiness, "probe_engine", lambda url: probe)
    monkeypatch.setattr(readiness, "snapshot", lambda supplied: result)
    response = client.get("/ready")
    assert response.status_code == code and response.json() == result
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/me").status_code == 401
