"""Native backend startup must reject signing keys copied from the templates."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

from auth_methods import backend_jwt_secret


BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("template", "setting", "provider"),
    [
        (BACKEND / ".env.example", "BACKEND_JWT_SECRET", "github"),
        (BACKEND.parent / "frontend" / ".env.example", "AUTH_SECRET", "local"),
    ],
)
def test_example_secret_stops_app_before_database_setup(tmp_path, template, setting, provider):
    example = dotenv_values(template)[setting]
    assert example
    database = tmp_path / "map.db"
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=BACKEND,
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "ENV": "development",
            "VARDRMAP_AUTH_METHODS": provider,
            "BACKEND_JWT_SECRET": example,
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "Replace the example BACKEND_JWT_SECRET" in result.stderr
    assert example not in result.stderr + result.stdout
    assert not database.exists()


def test_generated_backend_key_is_preserved(monkeypatch):
    generated = secrets.token_hex(32)
    monkeypatch.setenv("BACKEND_JWT_SECRET", generated)
    assert backend_jwt_secret() == generated
