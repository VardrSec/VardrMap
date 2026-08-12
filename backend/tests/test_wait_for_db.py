"""Tests for the startup readiness gate.

The failure this guards against is Railway starting the app container while
Postgres is still in recovery. These tests drive `wait_for_db` against a stubbed
engine so the retry, success, and timeout paths are covered without needing a
real database that can be stopped mid-test.
"""
import time

import pytest

import wait_for_db as wfd


class _FakeConn:
    def __init__(self, fail_times: list[int], calls: dict):
        self._fail_times = fail_times
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, _stmt):
        self._calls["n"] += 1
        if self._calls["n"] in self._fail_times:
            raise OSError("connection failed: the database system is starting up")
        return None


class _FakeEngine:
    """Fails `SELECT 1` on the attempt numbers listed in `fail_on`."""

    def __init__(self, fail_on: list[int]):
        self.fail_on = fail_on
        self.calls = {"n": 0}

    def connect(self):
        return _FakeConn(self.fail_on, self.calls)


@pytest.fixture
def no_sleep(monkeypatch):
    """Keep retry tests instant."""
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def test_returns_immediately_when_database_is_up(monkeypatch, no_sleep):
    monkeypatch.setattr(wfd, "engine", _FakeEngine(fail_on=[]))
    assert wfd.wait_for_db(timeout=5, interval=0) == 1


def test_retries_until_database_finishes_starting(monkeypatch, no_sleep):
    """The real scenario: a few 'starting up' failures, then success."""
    monkeypatch.setattr(wfd, "engine", _FakeEngine(fail_on=[1, 2, 3]))
    assert wfd.wait_for_db(timeout=30, interval=0) == 4


def test_raises_when_database_never_becomes_available(monkeypatch, no_sleep):
    """A genuinely unreachable database must fail the deploy, not hang forever."""
    monkeypatch.setattr(wfd, "engine", _FakeEngine(fail_on=list(range(1, 500))))
    with pytest.raises(OSError, match="starting up"):
        wfd.wait_for_db(timeout=0, interval=0)


def test_start_sh_waits_before_running_migrations():
    """Ordering is the whole point — the gate must precede alembic."""
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "start.sh"
    body = script.read_text(encoding="utf-8")
    assert "python wait_for_db.py" in body, "start.sh must run the readiness gate"
    assert body.index("wait_for_db.py") < body.index("alembic upgrade head"), (
        "the readiness gate must run before migrations, or it does nothing"
    )
