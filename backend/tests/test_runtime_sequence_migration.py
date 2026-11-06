"""Additive SQLite migration preservation; PostgreSQL roles are checked in CI."""

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, create_engine, inspect, select


def revision(name):
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location(
        "sequence_migration_" + name[:4], path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_sequence_revision_preserves_exact_v1_incarnation_and_refuses_downgrade(
    tmp_path,
):
    old, new = (
        revision("0039_managed_runtime.py"),
        revision("0040_managed_runtime_sequence.py"),
    )
    assert new.down_revision == old.revision
    engine = create_engine("sqlite:///" + (tmp_path / "migration.db").as_posix())
    now = datetime(2026, 11, 2, 18)
    identity = {
        "daemon_id": "d",
        "container_id": "1" * 64,
        "started_at": "2026-11-02T18:00:00.000000001Z",
    }
    original = dict(
        id="runtime-1",
        owner="owner",
        enrollment_id="enrollment",
        enrollment_revision=1,
        api_key_id="key",
        principal_sha256="a" * 64,
        runner_id="runner",
        origin="https://map.example.test",
        identity=identity,
        runtime_sha256="b" * 64,
        physical_sha256="c" * 64,
        owner_nonce="d" * 64,
        capability_sha256="e" * 64,
        ttl_seconds=60,
        registered_at=now,
        expires_at=now + timedelta(seconds=60),
        revoked=False,
        retired=False,
    )
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            old.upgrade()
            table = Table("managed_runtimes", MetaData(), autoload_with=connection)
            connection.execute(table.insert().values(**original))
            bound = {
                **original,
                "id": "runtime-2",
                "physical_sha256": "f" * 64,
                "owner_nonce": "1" * 64,
                "capability_sha256": "2" * 64,
                "job_id": "job-1",
                "contract_id": "contract-1",
                "attempt_id": "attempt-1",
                "fence": 1,
                "contract_sha256": "3" * 64,
                "bound_at": now,
                "confirmed_at": now,
                "retired": True,
                "report_sha256": "4" * 64,
            }
            connection.execute(table.insert().values(**bound))
            before = [
                dict(row)
                for row in connection.execute(
                    select(table).order_by(table.c.id)
                ).mappings()
            ]
            identity_bytes = connection.exec_driver_sql(
                "SELECT id, CAST(identity AS TEXT) FROM managed_runtimes ORDER BY id"
            ).all()
            unique = {
                tuple(item["column_names"])
                for item in inspect(connection).get_unique_constraints(table.name)
            }
            new.upgrade()
            migrated = Table("managed_runtimes", MetaData(), autoload_with=connection)
            after = [
                dict(row)
                for row in connection.execute(
                    select(migrated).order_by(migrated.c.id)
                ).mappings()
            ]
            assert (
                connection.exec_driver_sql(
                    "SELECT id, CAST(identity AS TEXT) FROM managed_runtimes ORDER BY id"
                ).all()
                == identity_bytes
            )
            for old_row, new_row in zip(before, after, strict=True):
                assert {key: new_row[key] for key in old_row} == old_row
                assert (
                    new_row["max_attempts"]
                    is new_row["active_sequence"]
                    is new_row["retirement_receipt"]
                    is None
                )
                assert new_row["last_sequence"] == 0
            assert {
                tuple(item["column_names"])
                for item in inspect(connection).get_unique_constraints(migrated.name)
            } == unique
            assert {
                item["name"]
                for item in inspect(connection).get_check_constraints(migrated.name)
            } == {"ck_managed_runtime_v2_binding", "ck_managed_runtime_v2_retirement"}
            history = Table(
                "managed_runtime_attempts", MetaData(), autoload_with=connection
            )
            assert connection.execute(select(history)).all() == []
            assert inspect(connection).get_pk_constraint(history.name)[
                "constrained_columns"
            ] == ["runtime_id", "runtime_sequence"]
            with pytest.raises(RuntimeError, match="Retain runtime sequence history"):
                new.downgrade()
            assert [
                dict(row)
                for row in connection.execute(
                    select(migrated).order_by(migrated.c.id)
                ).mappings()
            ] == after
    engine.dispose()
