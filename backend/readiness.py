"""Value-free API readiness; never applies migrations or runs authorization tests."""

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from database_options import connection_args
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool


@lru_cache(maxsize=1)
def probe_engine(database_url: URL) -> Engine:
    # A separate connection budget keeps probes out of the application's pool.
    # Preserve its URL/TLS policy; PostgreSQL probes are session-read-only.
    args = connection_args(str(database_url))
    if database_url.get_backend_name() == "postgresql":
        args.update(connect_timeout=3)
        args["options"] += (
            " -c statement_timeout=3000 -c default_transaction_read_only=on"
        )
    elif database_url.get_backend_name() == "sqlite":
        args["timeout"] = 3
    return create_engine(database_url, connect_args=args, poolclass=NullPool)


@lru_cache(maxsize=1)
def expected_heads() -> tuple[str, ...]:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parent / "migrations"))
    return tuple(sorted(scripts.get_heads()))


def snapshot(probe: Engine) -> dict:
    checks = {"database": "unavailable", "migrations": "not_checked"}
    try:
        with probe.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            checks["database"] = "ok"
            try:
                expected = expected_heads()
                if len(expected) != 1:
                    checks["migrations"] = "unavailable"
                else:
                    current = tuple(
                        sorted(
                            MigrationContext.configure(connection).get_current_heads()
                        )
                    )
                    checks["migrations"] = (
                        "current" if current == expected else "not_current"
                    )
            except Exception:
                # Packaging/metadata errors must not expose revision paths or DSNs.
                checks["migrations"] = "unavailable"
    except (SQLAlchemyError, OSError):
        checks = {"database": "unavailable", "migrations": "not_checked"}
    return {
        "schema_version": 1,
        "component": "vardrmap-api",
        "status": "ready"
        if checks == {"database": "ok", "migrations": "current"}
        else "not_ready",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
