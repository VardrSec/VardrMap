"""Local cookies preserve existing tenant checks, and never bypass CSRF/revocation."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import local_auth
from auth_methods import auth_methods
from db import Base, get_db
from main import app
from models import (
    LocalBootstrap,
    LocalCredential,
    LocalSession,
    OrganizationMember,
    User,
)
from tests.conftest import mint_token

PASSWORD = "fixture local password 783!"
NEW_PASSWORD = "replacement local password 924!"
ORIGIN = "https://workspace.example"


@pytest.fixture
def local_setup(monkeypatch):
    monkeypatch.setenv("VARDRMAP_AUTH_METHODS", "github,local")
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    previous = dict(app.dependency_overrides)

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app, base_url="https://api.example") as client:
        yield client, sessions
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    engine.dispose()


def initialize(sessions):
    with sessions() as db:
        return local_auth.bootstrap(db, "operator", PASSWORD)


def login(client, password=PASSWORD):
    return client.post(
        "/auth/local/login",
        json={"username": "Operator", "password": password},
        headers={"Origin": ORIGIN},
    )


def csrf_headers(client):
    result = client.get("/auth/local/session")
    assert result.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrfToken"]}


def test_bootstrap_is_once_and_uses_existing_owner_membership(local_setup):
    client, sessions = local_setup
    user_id = initialize(sessions)
    assert user_id.startswith("local:")
    with sessions() as db:
        assert (
            db.query(OrganizationMember)
            .filter_by(github_id=user_id, role="owner")
            .count()
            == 1
        )
        encoded = db.get(LocalCredential, user_id).password_hash
        assert encoded.startswith("$argon2id$") and PASSWORD not in encoded
        with pytest.raises(ValueError, match="already complete"):
            local_auth.bootstrap(db, "second-owner", NEW_PASSWORD)
        assert (
            db.query(LocalBootstrap).count() == db.query(LocalCredential).count() == 1
        )
        assert db.query(User).count() == 1
    assert (
        client.post("/auth/local/bootstrap", json={"username": "attacker"}).status_code
        == 404
    )


@pytest.mark.parametrize("password", ["short", " " * 16, "x" * 129])
def test_bootstrap_rejects_weak_length_before_claiming_singleton(local_setup, password):
    _, sessions = local_setup
    with sessions() as db:
        with pytest.raises(ValueError):
            local_auth.bootstrap(db, "operator", password)
        assert db.query(LocalBootstrap).count() == db.query(User).count() == 0


def test_secure_cookie_contains_the_only_session_secret(local_setup):
    client, sessions = local_setup
    user_id = initialize(sessions)
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=28800" in cookie and "Path=/" in cookie and "Domain=" not in cookie
    raw = client.cookies.get(local_auth.COOKIE_NAME)
    assert raw and raw not in response.text and PASSWORD not in response.text
    with sessions() as db:
        record = db.get(LocalSession, local_auth.digest(raw))
        assert record.user_id == user_id and raw != record.token_hash
    session = client.get("/auth/local/session")
    assert session.status_code == 200 and session.json()["authMethod"] == "local"
    assert "backendToken" not in session.json() and raw not in session.text
    assert session.headers["cache-control"] == "no-store"
    assert client.get("/me").json()["github_id"] == user_id


def test_local_mode_does_not_bypass_ownership_or_runner_scopes(local_setup):
    client, sessions = local_setup
    initialize(sessions)
    foreign_headers = {"Authorization": "Bearer " + mint_token("other-user")}
    foreign = client.post(
        "/engagements", json={"name": "Other workspace"}, headers=foreign_headers
    ).json()["id"]
    assert login(client).status_code == 200
    headers = csrf_headers(client)
    own = client.post("/engagements", json={"name": "Local workspace"}, headers=headers)
    assert own.status_code == 200
    assert client.get("/engagements/" + foreign).status_code == 404
    assert (
        client.patch(
            "/engagements/" + foreign, json={"name": "changed"}, headers=headers
        ).status_code
        == 404
    )
    key = client.post(
        "/auth/apikeys", json={"scope": "runner"}, headers=headers
    ).json()["token"]
    assert (
        client.get("/me", headers={"Authorization": "Bearer " + key}).status_code == 200
    )
    assert (
        client.get(
            "/engagements/" + own.json()["id"] + "/evidence",
            headers={"Authorization": "Bearer " + key},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": ORIGIN},
        {"Origin": "https://evil.example", "X-CSRF-Token": "wrong"},
    ],
)
def test_cookie_authenticated_writes_require_origin_and_csrf(local_setup, headers):
    client, sessions = local_setup
    initialize(sessions)
    assert login(client).status_code == 200
    assert (
        client.post(
            "/engagements", json={"name": "forged"}, headers=headers
        ).status_code
        == 403
    )
    assert client.post("/auth/local/logout", headers=headers).status_code == 403
    assert client.get("/me").status_code == 200


def test_wrong_origin_cannot_reuse_a_valid_csrf_token(local_setup):
    client, sessions = local_setup
    initialize(sessions)
    login(client)
    headers = csrf_headers(client)
    headers["Origin"] = "null"
    assert (
        client.post(
            "/engagements", json={"name": "forged"}, headers=headers
        ).status_code
        == 403
    )


def test_logout_revokes_server_session_and_clears_cookie(local_setup):
    client, sessions = local_setup
    initialize(sessions)
    login(client)
    raw = client.cookies.get(local_auth.COOKIE_NAME)
    headers = csrf_headers(client)
    assert client.post("/auth/local/logout", headers=headers).status_code == 200
    assert client.get("/me").status_code == 401
    assert (
        client.get(
            "/me", headers={"Cookie": local_auth.COOKIE_NAME + "=" + raw}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "field,delta",
    [("created_at", timedelta(hours=9)), ("last_seen_at", timedelta(minutes=31))],
)
def test_idle_and_absolute_expiration(local_setup, field, delta):
    client, sessions = local_setup
    initialize(sessions)
    login(client)
    with sessions() as db:
        record = db.query(LocalSession).one()
        if field == "created_at":
            record.expires_at = local_auth.now() - timedelta(seconds=1)
        else:
            record.last_seen_at = local_auth.now() - delta
        db.commit()
    assert client.get("/me").status_code == 401


def test_password_change_revokes_other_sessions_and_replaces_current_cookie(
    local_setup,
):
    client, sessions = local_setup
    initialize(sessions)
    login(client)
    first = client.cookies.get(local_auth.COOKIE_NAME)
    client.cookies.clear()
    login(client)
    second = client.cookies.get(local_auth.COOKIE_NAME)
    assert second != first
    changed = client.post(
        "/auth/local/password",
        headers=csrf_headers(client),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200
    assert client.cookies.get(local_auth.COOKIE_NAME) not in {first, second}
    assert (
        client.get(
            "/me", headers={"Cookie": local_auth.COOKIE_NAME + "=" + first}
        ).status_code
        == 401
    )
    assert client.get("/me").status_code == 200
    assert login(client, PASSWORD).status_code == 401
    assert login(client, NEW_PASSWORD).status_code == 200


def test_session_fixation_and_login_failures_are_generic(local_setup):
    client, sessions = local_setup
    initialize(sessions)
    assert (
        client.get(
            "/me", headers={"Cookie": local_auth.COOKIE_NAME + "=fixed"}
        ).status_code
        == 401
    )
    assert login(client, "incorrect").json() == {"detail": "Sign-in failed"}
    unknown = client.post(
        "/auth/local/login",
        headers={"Origin": ORIGIN},
        json={"username": "missing", "password": PASSWORD},
    )
    assert unknown.status_code == 401 and unknown.json() == {"detail": "Sign-in failed"}


def test_persistent_account_throttle_survives_separate_requests(local_setup):
    client, sessions = local_setup
    user_id = initialize(sessions)
    for _ in range(5):
        assert login(client, "incorrect").status_code == 401
    assert login(client).status_code == 401
    with sessions() as db:
        credential = db.get(LocalCredential, user_id)
        assert credential.failed_attempts == 5 and credential.locked_until is not None
        credential.locked_until = local_auth.now() - timedelta(seconds=1)
        db.commit()
    assert login(client).status_code == 200


def test_local_disabled_and_github_coexists_explicitly(local_setup, monkeypatch):
    client, sessions = local_setup
    initialize(sessions)
    assert login(client).status_code == 200
    monkeypatch.setenv("VARDRMAP_AUTH_METHODS", "github")
    assert login(client).status_code == 404
    assert client.get("/me").status_code in (401, 404)
    token = mint_token("github-user")
    assert (
        client.get("/me", headers={"Authorization": "Bearer " + token}).status_code
        == 200
    )
    monkeypatch.setenv("VARDRMAP_AUTH_METHODS", "local")
    assert (
        client.get("/me", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )


def test_github_jwt_cannot_impersonate_reserved_local_identity(local_setup):
    client, sessions = local_setup
    user_id = initialize(sessions)
    assert (
        client.get(
            "/me", headers={"Authorization": "Bearer " + mint_token(user_id)}
        ).status_code
        == 401
    )


def test_local_credentials_require_https_and_allowed_login_origin(local_setup):
    client, sessions = local_setup
    initialize(sessions)
    assert (
        client.post(
            "http://api.example/auth/local/login",
            headers={"Origin": ORIGIN},
            json={"username": "operator", "password": PASSWORD},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/auth/local/login", json={"username": "operator", "password": PASSWORD}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/auth/local/login",
            headers={"Origin": "https://evil.example"},
            json={"username": "operator", "password": PASSWORD},
        ).status_code
        == 403
    )


def test_validation_error_never_echoes_password(local_setup):
    client, _ = local_setup
    secret = "private-request-value" * 10
    response = client.post(
        "/auth/local/login",
        headers={"Origin": ORIGIN},
        json={"username": "operator", "password": secret},
    )
    assert response.status_code == 422 and secret not in response.text


@pytest.mark.parametrize("setting", ["", "github,", "local,unknown"])
def test_invalid_provider_settings_fail_closed(monkeypatch, setting):
    monkeypatch.setenv("VARDRMAP_AUTH_METHODS", setting)
    with pytest.raises(RuntimeError):
        auth_methods()


def test_local_recovery_revokes_browser_sessions_without_reassigning_ownership(
    local_setup, monkeypatch, capsys
):
    import local_accounts

    client, sessions = local_setup
    user_id = initialize(sessions)
    login(client)
    monkeypatch.setattr(local_accounts, "SessionLocal", sessions)
    monkeypatch.setattr(local_accounts.getpass, "getpass", lambda prompt: NEW_PASSWORD)
    monkeypatch.setattr(
        "sys.argv", ["local_accounts", "reset-password", "--username", "operator"]
    )
    local_accounts.main()
    assert PASSWORD not in capsys.readouterr().out
    assert client.get("/me").status_code == 401
    assert login(client, NEW_PASSWORD).status_code == 200
    assert client.get("/me").json()["github_id"] == user_id


def test_bootstrap_cli_never_accepts_password_arguments(local_setup, monkeypatch):
    import local_accounts

    monkeypatch.setattr(
        "sys.argv",
        ["local_accounts", "init", "--username", "operator", "--password", "not-used"],
    )
    with pytest.raises(SystemExit) as raised:
        local_accounts.main()
    assert raised.value.code == 2


def test_login_ip_rate_limit(local_setup, monkeypatch):
    from limiter import limiter

    client, _ = local_setup
    limiter._storage.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    try:
        responses = [login(client, "incorrect") for _ in range(11)]
        assert responses[-1].status_code == 429
        assert all(result.status_code in (401, 429) for result in responses)
    finally:
        limiter._storage.reset()


def test_csrf_is_bound_to_rotated_session(local_setup):
    client, sessions = local_setup
    initialize(sessions)
    login(client)
    previous = csrf_headers(client)
    login(client)
    assert (
        client.post(
            "/engagements", headers=previous, json={"name": "stale csrf"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/engagements", headers=csrf_headers(client), json={"name": "current csrf"}
        ).status_code
        == 200
    )


def test_cookie_session_requires_existing_local_credential(local_setup):
    client, sessions = local_setup
    user_id = initialize(sessions)
    login(client)
    with sessions() as db:
        db.delete(db.get(LocalCredential, user_id))
        db.commit()
    assert client.get("/me").status_code == 401


def test_old_argon_parameters_are_upgraded_after_password_verification(local_setup):
    from argon2 import PasswordHasher

    client, sessions = local_setup
    user_id = initialize(sessions)
    with sessions() as db:
        credential = db.get(LocalCredential, user_id)
        credential.password_hash = PasswordHasher(
            memory_cost=8192, time_cost=1, parallelism=1
        ).hash(PASSWORD)
        db.commit()
    assert login(client).status_code == 200
    with sessions() as db:
        assert not local_auth.PASSWORD_HASHER.check_needs_rehash(
            db.get(LocalCredential, user_id).password_hash
        )


def test_local_routes_reject_github_bearer_as_local_session(local_setup):
    client, _ = local_setup
    headers = {"Authorization": "Bearer " + mint_token("github-user")}
    assert client.get("/auth/local/session", headers=headers).status_code == 401
    assert client.post("/auth/local/logout", headers=headers).status_code == 401


def test_malformed_unicode_credentials_are_generic_failures(local_setup):
    import json

    client, sessions = local_setup
    initialize(sessions)
    for payload in (
        {"username": "operator", "password": "\ud800"},
        {"username": "\ud800", "password": PASSWORD},
    ):
        response = client.post("/auth/local/login", headers={"Origin": ORIGIN, "Content-Type": "application/json"},
                               content=json.dumps(payload).encode())
        assert response.status_code in (401, 422)
        assert response.json()["detail"] in {"Sign-in failed", "Invalid authentication request"}
    with sessions() as db:
        with pytest.raises(ValueError):
            local_auth.bootstrap(db, "bad-input", "a passphrase with \ud800")


def test_malformed_csrf_is_rejected_without_an_exception(local_setup):
    client, sessions = local_setup
    initialize(sessions)
    login(client)
    assert (
        client.post(
            "/auth/local/logout",
            headers=[(b"Origin", ORIGIN.encode()), (b"X-CSRF-Token", b"\xe9")],
        ).status_code
        == 403
    )
