"""Subprocess scenarios isolated from the SQLite suite's global app fixtures."""

import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from time import monotonic
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from db import SessionLocal, engine
from local_auth import (
    COOKIE_NAME,
    bootstrap,
    csrf_token,
    digest,
    issue_session,
    now,
    resolve_session,
    verify_login,
)
from models import LocalCredential, LocalSession
import local_accounts

PASSWORD = "concurrency fixture password 937!"
REPLACEMENT = "replacement fixture password 482!"


def reset_password():
    with (
        patch.object(
            sys, "argv", ["local_accounts", "reset-password", "--username", "operator"]
        ),
        patch.object(local_accounts.getpass, "getpass", return_value=REPLACEMENT),
    ):
        local_accounts.main()


def request(raw):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "server": ("api.example", 443),
            "path": "/me",
            "query_string": b"",
            "headers": [(b"cookie", (COOKIE_NAME + "=" + raw).encode())],
        }
    )


def assert_revoked(raw):
    with SessionLocal() as db:
        try:
            resolve_session(request(raw), db)
        except HTTPException as error:
            assert error.status_code == 401
        else:
            raise AssertionError("Revoked session still authorizes a request")


def failed_logins(user_id):
    start = Barrier(8)

    def attempt(_):
        start.wait(timeout=10)
        with SessionLocal() as db:
            try:
                verify_login(db, "operator", "incorrect fixture password")
            except HTTPException as error:
                return error.status_code
            raise AssertionError("Wrong password accepted")

    began = monotonic()
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(attempt, range(8))) == [401] * 8
    elapsed = monotonic() - began
    with SessionLocal() as db:
        credential = db.get(LocalCredential, user_id)
        assert credential.failed_attempts == 5
        assert credential.locked_until > now()
        assert db.query(LocalSession).count() == 0
        try:
            verify_login(db, "operator", PASSWORD)
        except HTTPException as error:
            assert error.status_code == 401
        else:
            raise AssertionError("Locked account accepted a password")
    print(
        f"Eight simultaneous failures serialized without lost counts in {elapsed:.3f}s"
    )


def login_recovery(user_id):
    verified, release = Event(), Event()

    def held_login():
        with SessionLocal() as db:
            credential = verify_login(db, "operator", PASSWORD)
            verified.set()
            assert release.wait(timeout=15)
            return issue_session(db, credential.user_id, Response())

    with ThreadPoolExecutor(max_workers=2) as pool:
        login = pool.submit(held_login)
        assert verified.wait(timeout=10)
        recovery = pool.submit(reset_password)
        try:
            # Prove recovery is waiting on the credential lock, not just scheduled.
            deadline = monotonic() + 10
            waiting = False
            while monotonic() < deadline:
                with engine.connect() as conn:
                    waiting = (
                        conn.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%local_credentials%FOR UPDATE%'"
                            )
                        )
                        > 0
                    )
                if waiting:
                    break
                Event().wait(0.02)
            assert waiting, "Recovery did not contend on the credential lock"
        finally:
            release.set()
        raw = login.result(timeout=10)
        recovery.result(timeout=10)
    assert_revoked(raw)
    with SessionLocal() as db:
        assert verify_login(db, "operator", REPLACEMENT).user_id == user_id
    print("Recovery waited for login issuance and revoked the resulting session")


def password_changes(user_id):
    from main import app

    with SessionLocal() as db:
        tokens = [issue_session(db, user_id, Response()) for _ in range(2)]
    start = Barrier(2)

    def change(index):
        with TestClient(app, base_url="https://api.example") as client:
            start.wait(timeout=10)
            response = client.post(
                "/auth/local/password",
                headers={
                    "Cookie": COOKIE_NAME + "=" + tokens[index],
                    "Origin": "https://workspace.example",
                    "X-CSRF-Token": csrf_token(tokens[index]),
                },
                json={
                    "current_password": PASSWORD,
                    "new_password": REPLACEMENT + str(index),
                },
            )
            return response.status_code, client.cookies.get(COOKIE_NAME), index

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, range(2)))
    assert sorted(row[0] for row in results) == [200, 401], results
    winner = next(row for row in results if row[0] == 200)
    for raw in tokens:
        assert_revoked(raw)
    with SessionLocal() as db:
        assert db.query(LocalSession).count() == 1
        assert resolve_session(request(winner[1]), db)["github_id"] == user_id
        assert (
            verify_login(db, "operator", REPLACEMENT + str(winner[2])).user_id
            == user_id
        )
    print(
        "Concurrent password changes produced one winner and revoked both old cookies"
    )


def active_request(user_id):
    with SessionLocal() as db:
        raw = issue_session(db, user_id, Response())
        db.query(LocalSession).filter_by(token_hash=digest(raw)).update(
            {"last_seen_at": now() - timedelta(minutes=2)}
        )
        db.commit()
    with SessionLocal() as active:
        event.listen(active, "before_flush", lambda *_: reset_password(), once=True)
        try:
            resolve_session(request(raw), active)
        except HTTPException as error:
            assert error.status_code == 401
        else:
            raise AssertionError("Concurrent revocation was not rejected")
    assert_revoked(raw)
    with SessionLocal() as db:
        assert db.query(LocalSession).count() == 0
    print(
        "Revocation during activity refresh returned unauthorized without recreating a session"
    )


if __name__ == "__main__":
    try:
        with SessionLocal() as db:
            user_id = bootstrap(db, "operator", PASSWORD)
        {
            "failed_logins": failed_logins,
            "login_recovery": login_recovery,
            "password_changes": password_changes,
            "active_request": active_request,
        }[sys.argv[1]](user_id)
    finally:
        engine.dispose()
