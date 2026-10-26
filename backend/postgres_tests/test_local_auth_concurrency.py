"""Exercise credential row locks and revocation against migrated PostgreSQL."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_migrations import BACKEND, database, migrate  # noqa: F401


@pytest.mark.parametrize(
    "scenario",
    ["failed_logins", "login_recovery", "password_changes", "active_request"],
)
def test_local_auth_concurrency(database, scenario):  # noqa: F811 - imported pytest fixture
    _, url = database
    migrate(url, "upgrade", "head")
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("local_auth_concurrency_scenarios.py")),
            scenario,
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "DATABASE_URL": url,
            "ENV": "staging",
            "VARDRMAP_AUTH_METHODS": "github,local",
            "ALLOWED_ORIGINS": "https://workspace.example",
            "BACKEND_JWT_SECRET": "concurrency-fixture-secret-at-least-32-characters",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout.strip())
