"""Real PostgreSQL checks in disposable schemas of a dedicated test database.

Every test runs twice: as the CI administrator and as a plain login role with no
SUPERUSER, CREATEDB, CREATEROLE, REPLICATION or BYPASSRLS that only owns its schema.
The VardrSec distribution runs the API and these migrations as such a role, so a
migration that needs superuser (for example CREATE EXTENSION) fails here first.
"""

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


ROLE_ATTRIBUTES = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
ROLE_FLAGS = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")


@pytest.fixture(params=["administrator", "application_role"])
def database(request):
    raw = os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    url = make_url(normalize_url(raw))
    assert url.get_backend_name() == "postgresql"
    assert (url.database or "").startswith("vardrmap_test")
    admin = create_engine(url, connect_args=connection_args(str_url(url)))
    schema = "migration_" + uuid.uuid4().hex
    role = None
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        if request.param == "application_role":
            role = "vardrmap_ci_" + uuid.uuid4().hex[:12]
            password = "fixture-" + uuid.uuid4().hex
            conn.execute(
                text(f"CREATE ROLE \"{role}\" LOGIN {ROLE_ATTRIBUTES} PASSWORD '{password}'")
            )
            conn.execute(text(f'GRANT CONNECT ON DATABASE "{url.database}" TO "{role}"'))
            conn.execute(text(f'GRANT USAGE, CREATE ON SCHEMA "{schema}" TO "{role}"'))
            flags = conn.execute(
                text(f"SELECT {', '.join(ROLE_FLAGS)} FROM pg_roles WHERE rolname = :r"),
                {"r": role},
            ).one()
            assert not any(flags), "The restricted fixture role is not restricted"
            url = url.set(username=role, password=password)
    isolated = str_url(url.update_query_dict({"options": f"-c search_path={schema}"}))
    engine = create_engine(isolated, connect_args=connection_args(isolated))
    try:
        yield engine, isolated
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            if role:
                conn.execute(text(f'DROP OWNED BY "{role}"'))
                conn.execute(text(f'DROP ROLE "{role}"'))
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
    with engine.connect() as conn:
        # Every object migrations created belongs to the connecting login, whichever it is.
        assert conn.scalar(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname = current_schema() "
                "AND tableowner <> current_user"
            )
        ) == 0
    # Read every ORM-mapped column against the migrated schema. Unlike create_all
    # fixtures, this catches columns missing from migration history.
    code = """
from sqlalchemy import select, text
from db import Base, engine
from main import app
from fastapi.testclient import TestClient
with engine.connect() as conn:
    for table in Base.metadata.sorted_tables:
        conn.execute(select(table).limit(0))
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
    ready = client.get('/ready')
    assert ready.status_code == 200, ready.text
    assert ready.json()['checks'] == {'database': 'ok', 'migrations': 'current'}
from readiness import probe_engine
with probe_engine(engine.url).connect() as probe:
    assert probe.scalar(text('SHOW default_transaction_read_only')) == 'on'
    assert probe.scalar(text('SHOW statement_timeout')) == '3s'
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


def test_readiness_does_not_upgrade_an_old_schema(database):
    from readiness import probe_engine, snapshot

    engine, url = database
    migrate(url, "upgrade", "0001baseline")
    result = snapshot(probe_engine(make_url(url)))
    assert result["status"] == "not_ready"
    assert result["checks"] == {"database": "ok", "migrations": "not_current"}
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0001baseline"


def test_assessment_migration_roundtrip_and_provenance_retention(database):
    engine, url = database
    migrate(url, "upgrade", "0026dalfox")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (github_id, username) VALUES ('fixture', 'fixture')"))
        conn.execute(text("INSERT INTO programs (id, owner_github_id, name) VALUES ('eng', 'fixture', 'Fixture')"))
        conn.execute(text("INSERT INTO authorization_test_cases (id, program_id, owner_github_id, name, test_case_id, spec, created_at) VALUES ('case', 'eng', 'fixture', 'Fixture', 'logical-case', '{}', NOW())"))
        conn.execute(text("INSERT INTO scan_jobs (id, program_id, owner_github_id, tool_type, target_source, created_at) VALUES ('job', 'eng', 'fixture', 'vardrgate_api_test', 'scope', NOW())"))
        conn.execute(text("INSERT INTO evidence (id, program_id, kind, body, created_at) VALUES ('proof', 'eng', 'tool_result', 'original retained evidence', NOW())"))
    # Exercise this older migration's rollback before the credential-preserving
    # local-auth boundary, whose automatic downgrade is deliberately refused.
    migrate(url, "upgrade", "0030agentproposals")
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT job_id FROM evidence WHERE id='proof'")) is None
        assert conn.scalar(text("SELECT assessment FROM scan_jobs WHERE id='job'")) is None
        conn.execute(text("UPDATE evidence SET job_id='job', case_id='case', case_ref='logical-case', identity_id='OwnerA' WHERE id='proof'"))
        # Deleting a job/case preserves the retained proof and logical provenance.
        conn.execute(text("DELETE FROM scan_jobs WHERE id='job'"))
        conn.execute(text("DELETE FROM authorization_test_cases WHERE id='case'"))
        row = conn.execute(text("SELECT job_id, case_id, case_ref, identity_id, body FROM evidence WHERE id='proof'")).one()
        assert tuple(row) == (None, None, 'logical-case', 'OwnerA', 'original retained evidence')
    migrate(url, "downgrade", "0026dalfox")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT body FROM evidence WHERE id='proof'")) == "original retained evidence"
    migrate(url, "upgrade", "head")
    assert "job_id" in {c["name"] for c in inspect(engine).get_columns("evidence")}


def test_unstamped_nonempty_database_is_refused(database):
    engine, url = database
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated_data (value text)"))
        conn.execute(text("INSERT INTO unrelated_data VALUES ('keep me')"))
    result = migrate(url, "upgrade", "head", success=False)
    assert "Nonempty unstamped database" in result.stderr
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT value FROM unrelated_data")) == "keep me"


def test_local_bootstrap_race_preserves_existing_users(database):
    engine, url = database
    migrate(url, "upgrade", "head")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (github_id, username) VALUES ('existing-github', 'Existing owner')"))
    code = """
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from db import SessionLocal, engine
from local_auth import bootstrap
def create(name):
    with SessionLocal() as db:
        try:
            return bootstrap(db, name, 'concurrent fixture passphrase 937!')
        except ValueError:
            return None
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(create, ['operator-one', 'operator-two']))
assert sum(result is not None for result in results) == 1
with engine.connect() as conn:
    assert conn.scalar(text('SELECT count(*) FROM local_bootstrap')) == 1
    assert conn.scalar(text('SELECT count(*) FROM local_credentials')) == 1
    assert conn.scalar(text('SELECT count(*) FROM users')) == 2
    assert conn.scalar(text("SELECT username FROM users WHERE github_id='existing-github'")) == 'Existing owner'
    assert conn.scalar(text("SELECT count(*) FROM organization_members WHERE role='owner'")) == 1
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60,
        env={**os.environ, "DATABASE_URL": url, "ENV": "staging", "VARDRMAP_AUTH_METHODS": "local"},
    )
    assert result.returncode == 0, result.stderr
    downgrade = migrate(url, "downgrade", "0030agentproposals", success=False)
    assert "restore a verified backup" in downgrade.stderr
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM local_credentials")) == 1
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0031localauth"


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
