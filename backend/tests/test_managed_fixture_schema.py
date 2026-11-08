"""Cross-dialect fixture DDL must preserve real history constraints; no server."""

from datetime import datetime

import pytest
from sqlalchemy import (
    MetaData,
    create_engine,
    create_mock_engine,
    event,
    inspect,
    select,
)
from sqlalchemy.exc import IntegrityError

from models import Base
from tests.test_managed_issuance import create_fixture_schema


EXPECTED = {
    ("fk_managed_runtime_head", ("id", "head_sequence", "mode")),
    ("fk_managed_runtime_active", ("id", "active_sequence", "mode")),
    ("fk_managed_runtime_attempt_parent", ("runtime_id", "runtime_mode")),
    (
        "fk_managed_runtime_predecessor",
        ("runtime_id", "previous_sequence", "runtime_mode"),
    ),
}


def foreign_keys(engine):
    return {
        (row["name"], tuple(row["constrained_columns"]))
        for name in ("managed_runtimes", "managed_runtime_attempts")
        for row in inspect(engine).get_foreign_keys(name)
    }


def test_fixture_keeps_four_history_foreign_keys_after_postgresql_ddl(tmp_path):
    source = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(source)
    before = create_engine("sqlite:///" + (tmp_path / "before.db").as_posix())
    after = create_engine("sqlite:///" + (tmp_path / "after.db").as_posix())
    event.listen(
        after, "connect", lambda dbapi, _: dbapi.execute("PRAGMA foreign_keys=ON")
    )
    try:
        create_fixture_schema(before, metadata=source)
        assert foreign_keys(before) == EXPECTED
        # Exercise actual PostgreSQL DDL generation without connecting to a server.
        source.create_all(
            create_mock_engine("postgresql://", lambda *a, **k: None), checkfirst=False
        )
        create_fixture_schema(after, metadata=source)
        assert foreign_keys(after) == EXPECTED
        runtime, attempt = (
            source.tables["managed_runtimes"],
            source.tables["managed_runtime_attempts"],
        )
        # Storage-only rows exercise FK enforcement, never an issued permission.
        with after.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            connection.execute(
                runtime.insert().values(
                    id="fixture",
                    owner="fixture",
                    enrollment_id="fixture",
                    enrollment_revision=1,
                    api_key_id="fixture",
                    principal_sha256="1" * 64,
                    runner_id="fixture",
                    origin="https://fixture.example",
                    identity={},
                    runtime_sha256="2" * 64,
                    physical_sha256="3" * 64,
                    owner_nonce="4" * 64,
                    capability_sha256="5" * 64,
                    registered_at=datetime(2026, 11, 6),
                    revoked=False,
                    retired=False,
                    mode="persistent",
                    admission_snapshot={},
                    admission_sha256="6" * 64,
                    last_sequence=1,
                    head_sequence=1,
                    active_sequence=1,
                    new_work_disabled=False,
                )
            )
            connection.execute(
                attempt.insert().values(
                    runtime_id="fixture",
                    runtime_sequence=1,
                    runtime_mode="persistent",
                    previous_sequence=None,
                    job_id="fixture",
                    contract_id="fixture",
                    attempt_id="fixture",
                    fence=1,
                    contract_sha256="7" * 64,
                    bound_at=datetime(2026, 11, 6),
                )
            )
        with pytest.raises(IntegrityError), after.begin() as connection:
            connection.execute(
                attempt.delete().where(attempt.c.runtime_id == "fixture")
            )
        with after.connect() as connection:
            assert connection.execute(
                select(attempt.c.runtime_sequence)
            ).scalars().all() == [1]
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        before.dispose()
        after.dispose()
