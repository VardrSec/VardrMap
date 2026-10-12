"""Real PostgreSQL checks in disposable schemas of a dedicated test database."""

import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database_options import connection_args, normalize_url

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def database():
    raw = os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    url = make_url(normalize_url(raw))
    assert url.get_backend_name() == "postgresql"
    assert (url.database or "").startswith("vardrmap_test")
    admin = create_engine(url, connect_args=connection_args(str_url(url)))
    schema = "migration_" + uuid.uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = str_url(url.update_query_dict({"options": f"-c search_path={schema}"}))
    engine = create_engine(isolated, connect_args=connection_args(isolated))
    try:
        yield engine, isolated
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def str_url(url):
    return url.render_as_string(hide_password=False)


def migrate(url, *args, success=True):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url, "ENV": "staging"},
        capture_output=True,
        text=True,
        timeout=90,
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
    return result


def test_empty_database_migrates_and_app_starts(database):
    engine, url = database
    migrate(url, "upgrade", "head")
    migrate(url, "upgrade", "head")  # repeat startup is safe
    assert "evidence" in inspect(engine).get_table_names()
    # Read every ORM-mapped column against the migrated schema. Unlike create_all
    # fixtures, this catches columns missing from migration history.
    code = """
from sqlalchemy import select
from db import Base, engine
from main import app
from fastapi.testclient import TestClient
with engine.connect() as conn:
    for table in Base.metadata.sorted_tables:
        conn.execute(select(table).limit(0))
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DATABASE_URL": url,
            "ENV": "staging",
            "BACKEND_JWT_SECRET": "test-migrations-secret-at-least-32-characters",
        },
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_baseline_upgrade_preserves_records(database):
    engine, url = database
    migrate(url, "upgrade", "0001baseline")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (github_id, username) VALUES ('fixture', 'fixture')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO programs (id, owner_github_id, name) VALUES ('eng', 'fixture', 'Historical engagement')"
            )
        )
    migrate(url, "upgrade", "head")
    with engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT name FROM programs WHERE id='eng'"))
            == "Historical engagement"
        )


def test_unstamped_nonempty_database_is_refused(database):
    engine, url = database
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated_data (value text)"))
        conn.execute(text("INSERT INTO unrelated_data VALUES ('keep me')"))
    result = migrate(url, "upgrade", "head", success=False)
    assert "Nonempty unstamped database" in result.stderr
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT value FROM unrelated_data")) == "keep me"


def test_utc_connections_ignore_non_utc_database_default(database):
    engine, url = database
    # CI provisions America/Chicago as the database default. Use a raw connection
    # to check that fixture, then the application's policy on a separate engine.
    raw = create_engine(url, connect_args={"options": "-c timezone=America/Chicago"})
    with raw.connect() as conn:
        assert conn.scalar(text("SHOW timezone")) == "America/Chicago"
    raw.dispose()
    with engine.begin() as conn:
        assert conn.scalar(text("SHOW timezone")) == "UTC"
        conn.execute(text("CREATE TABLE dates (value timestamp without time zone)"))
        conn.execute(
            text("INSERT INTO dates VALUES (TIMESTAMPTZ '2026-12-31 00:00:00+00')")
        )
        assert (
            conn.scalar(text("SELECT value FROM dates")).isoformat()
            == "2026-12-31T00:00:00"
        )
