"""Block until Postgres accepts queries, then exit.

Railway starts the application container and the Postgres service concurrently.
The database is frequently still in recovery when the app's start command fires,
and Postgres answers the connection with `FATAL: the database system is starting
up` rather than refusing it. `alembic upgrade head` then exits non-zero, `set -e`
in start.sh kills the container, and the deploy crash-loops instead of waiting
out a condition that resolves itself in seconds.

Free-tier services amplify this: they cold-start on every deploy, so the app and
the database race from a stop every single time.

Reuses the engine from `db` deliberately — it already rewrites the URL scheme to
psycopg3 and applies `sslmode=require`, so the readiness check exercises exactly
the connection path the app will use rather than an approximation of it.
"""
import sys
import time

from sqlalchemy import text

from db import engine

DEFAULT_TIMEOUT = 120.0
DEFAULT_INTERVAL = 2.0


def wait_for_db(timeout: float = DEFAULT_TIMEOUT, interval: float = DEFAULT_INTERVAL) -> int:
    """Poll until a `SELECT 1` succeeds. Returns the number of attempts made.

    Raises the last connection error if `timeout` seconds elapse without success,
    so a genuinely unreachable database still fails the deploy loudly instead of
    hanging forever.
    """
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return attempt
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(interval)


if __name__ == "__main__":
    try:
        attempts = wait_for_db()
    except Exception as exc:
        print(f"Database unreachable after {DEFAULT_TIMEOUT:.0f}s: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Database ready (attempt {attempts}).")
