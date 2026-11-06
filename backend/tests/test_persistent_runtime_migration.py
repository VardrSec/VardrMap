"""Actual additive SQLite migration and enforced v3 history relationships."""

from datetime import datetime, timedelta

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError

from managed_runtime import check_identity
from managed_runtime_persistent import Persistent
from models import ManagedRuntime
from tests.test_runtime_sequence_migration import revision


def test_0041_preserves_finite_bytes_and_enforces_head_predecessor_and_parent(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "migration.db").as_posix())
    event.listen(
        engine, "connect", lambda dbapi, _: dbapi.execute("PRAGMA foreign_keys=ON")
    )
    now = datetime(2026, 11, 2, 18)
    identity = {"retained": "finite exact bytes", "unicode": "\u03bb"}
    old = dict(
        id="finite-v1",
        owner="owner",
        enrollment_id="enrolled",
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
        ttl_seconds=3600,
        registered_at=now,
        expires_at=now + timedelta(hours=1),
        revoked=False,
        retired=False,
    )
    new = revision("0041_persistent_runtime.py")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            revision("0039_managed_runtime.py").upgrade()
            revision("0040_managed_runtime_sequence.py").upgrade()
            runtimes = Table("managed_runtimes", MetaData(), autoload_with=connection)
            attempts = Table(
                "managed_runtime_attempts", MetaData(), autoload_with=connection
            )
            connection.execute(runtimes.insert().values(**old))
            second = {
                **old,
                "id": "finite-v2",
                "physical_sha256": "f" * 64,
                "owner_nonce": "1" * 64,
                "capability_sha256": "2" * 64,
                "max_attempts": 2,
                "last_sequence": 1,
                "active_sequence": 1,
            }
            connection.execute(runtimes.insert().values(**second))
            connection.execute(
                attempts.insert().values(
                    runtime_id="finite-v2",
                    runtime_sequence=1,
                    job_id="old-job",
                    contract_id="old-contract",
                    attempt_id="old-attempt",
                    fence=1,
                    contract_sha256="3" * 64,
                    bound_at=now,
                )
            )
            before = [
                dict(row)
                for row in connection.execute(
                    select(runtimes).order_by(runtimes.c.id)
                ).mappings()
            ]
            child_before = [
                dict(row) for row in connection.execute(select(attempts)).mappings()
            ]
            raw_before = connection.exec_driver_sql(
                "SELECT id,CAST(identity AS TEXT) FROM managed_runtimes ORDER BY id"
            ).all()
            new.upgrade()
            runtimes = Table("managed_runtimes", MetaData(), autoload_with=connection)
            attempts = Table(
                "managed_runtime_attempts", MetaData(), autoload_with=connection
            )
            after = [
                dict(row)
                for row in connection.execute(
                    select(runtimes).order_by(runtimes.c.id)
                ).mappings()
            ]
            for original, retained in zip(before, after, strict=True):
                assert {key: retained[key] for key in original} == original
                assert (
                    retained["mode"]
                    is retained["head_sequence"]
                    is retained["admission_snapshot"]
                    is None
                )
                assert retained["new_work_disabled"] is False
            child = connection.execute(select(attempts)).mappings().one()
            assert {key: child[key] for key in child_before[0]} == child_before[0]
            assert child["runtime_mode"] is child["previous_sequence"] is None
            assert (
                connection.exec_driver_sql(
                    "SELECT id,CAST(identity AS TEXT) FROM managed_runtimes ORDER BY id"
                ).all()
                == raw_before
            )
            assert {
                fk["name"] for fk in inspect(connection).get_foreign_keys(runtimes.name)
            } >= {"fk_managed_runtime_head", "fk_managed_runtime_active"}
            assert {
                fk["name"] for fk in inspect(connection).get_foreign_keys(attempts.name)
            } >= {"fk_managed_runtime_attempt_parent", "fk_managed_runtime_predecessor"}
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    # This storage-only fixture is not an issued execution permission.
    physical = dict(
        daemon_id="fixture",
        container_id="4" * 64,
        image_id="sha256:" + "5" * 64,
        project="fixture",
        started_at="2026-11-02T18:00:00.000000001Z",
        owner_nonce="6" * 64,
    )
    sha, key = check_identity(physical)
    row = ManagedRuntime(
        id="00000000-0000-0000-0000-000000000041",
        owner="owner",
        enrollment_id="enrolled",
        enrollment_revision=1,
        api_key_id="key",
        principal_sha256="7" * 64,
        runner_id="00000000-0000-0000-0000-000000000007",
        origin="https://map.example.test",
        identity=physical,
        runtime_sha256=sha,
        physical_sha256=key,
        owner_nonce=physical["owner_nonce"],
        capability_sha256="8" * 64,
        registered_at=now,
        ttl_seconds=None,
        expires_at=None,
        mode="persistent",
        max_attempts=None,
        idle_timeout_seconds=None,
        last_sequence=0,
        head_sequence=None,
        active_sequence=None,
        revoked=False,
        retired=False,
        new_work_disabled=False,
    )
    row.admission_snapshot = Persistent.public(row)
    row.admission_sha256 = row.admission_snapshot["admission_sha256"]
    with engine.begin() as connection:
        connection.execute(
            runtimes.insert().values(
                **{k: v for k, v in row.__dict__.items() if not k.startswith("_")}
            )
        )
        connection.execute(
            attempts.insert().values(
                runtime_id=row.id,
                runtime_sequence=1,
                runtime_mode="persistent",
                previous_sequence=None,
                job_id="new-job",
                contract_id="new-contract",
                attempt_id="new-attempt",
                fence=1,
                contract_sha256="9" * 64,
                bound_at=now,
            )
        )
        connection.execute(
            runtimes.update()
            .where(runtimes.c.id == row.id)
            .values(last_sequence=1, head_sequence=1, active_sequence=1)
        )
    for action in ("delete_head", "missing_predecessor", "missing_head"):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            if action == "delete_head":
                connection.execute(
                    attempts.delete().where(attempts.c.runtime_id == row.id)
                )
            elif action == "missing_head":
                connection.execute(
                    runtimes.update()
                    .where(runtimes.c.id == row.id)
                    .values(last_sequence=2, head_sequence=2, active_sequence=2)
                )
            else:
                connection.execute(
                    attempts.insert().values(
                        runtime_id=row.id,
                        runtime_sequence=3,
                        runtime_mode="persistent",
                        previous_sequence=2,
                        job_id="gap-job",
                        contract_id="gap-contract",
                        attempt_id="gap-attempt",
                        fence=1,
                        contract_sha256="a" * 64,
                        bound_at=now,
                    )
                )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(runtimes.c.last_sequence).where(runtimes.c.id == row.id)
            )
            == 1
        )
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    with pytest.raises(
        RuntimeError, match="Code-only rollback over v3 state is unsupported"
    ):
        new.downgrade()
    engine.dispose()
