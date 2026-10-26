"""Local credentials and revocable cookies reuse the existing user/tenant model."""

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from auth_methods import auth_methods
from fastapi import HTTPException, Request, Response
from models import LocalBootstrap, LocalCredential, LocalSession, User, new_uuid
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

COOKIE_NAME = "__Host-vardrmap.session"
SESSION_LIFETIME = timedelta(hours=8)
IDLE_LIFETIME = timedelta(minutes=30)
FAILURE_WINDOW = timedelta(minutes=15)
PASSWORD_HASHER = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID
)
_DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def require_local() -> None:
    if "local" not in auth_methods():
        raise HTTPException(status_code=404, detail="Not found")


def validate_password(password: str) -> None:
    if not 15 <= len(password) <= 128 or not password.strip():
        raise ValueError("Use a password or passphrase containing 15 to 128 characters")
    try:
        password.encode("utf-8")
    except UnicodeError:
        raise ValueError("Password must contain valid Unicode") from None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_token(raw_session: str) -> str:
    key = os.getenv("BACKEND_JWT_SECRET", "")
    if len(key) < 32:
        raise HTTPException(
            status_code=500, detail="Local authentication is not configured"
        )
    return hmac.new(
        key.encode(), b"vardrmap-csrf-v1:" + raw_session.encode(), hashlib.sha256
    ).hexdigest()


def check_transport(request: Request, *, write: bool) -> None:
    require_local()
    if request.url.scheme != "https":
        raise HTTPException(
            status_code=400, detail="Local authentication requires HTTPS"
        )
    if write:
        allowed = {
            origin.strip()
            for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(
                ","
            )
            if origin.strip()
        }
        if request.headers.get("origin") not in allowed:
            raise HTTPException(status_code=403, detail="Invalid request origin")


def bootstrap(db: Session, username: str, password: str) -> str:
    require_local()
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", username):
        raise ValueError(
            "Use a username of 3 to 64 ASCII letters, digits, dots, underscores or hyphens"
        )
    validate_password(password)
    encoded = PASSWORD_HASHER.hash(password)
    try:
        db.add(LocalBootstrap(id=1))
        db.flush()  # The singleton claim and account creation commit together.
        user_id = "local:" + new_uuid()
        db.add(User(github_id=user_id, username=username, email=""))
        db.flush()
        db.add(
            LocalCredential(user_id=user_id, username=username, password_hash=encoded)
        )
        from deps import personal_org

        personal_org(user_id, db)
        db.commit()
        return user_id
    except IntegrityError:
        db.rollback()
        raise ValueError(
            "Local bootstrap is already complete or the account cannot be created"
        ) from None


def verify_login(db: Session, username: str, password: str) -> LocalCredential:
    normalized = username.strip().lower()
    credential = (
        (
            db.query(LocalCredential)
            .filter_by(username=normalized)
            .with_for_update()
            .first()
        )
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", normalized)
        else None
    )
    instant = now()
    blocked = (
        credential is not None
        and credential.locked_until is not None
        and credential.locked_until > instant
    )
    encoded = (
        credential.password_hash
        if credential is not None and not blocked
        else _DUMMY_HASH
    )
    try:
        PASSWORD_HASHER.verify(encoded, password)
        verified = True
    except (VerificationError, InvalidHashError, UnicodeError):
        verified = False
    if credential is None or blocked:
        db.rollback()
        raise HTTPException(status_code=401, detail="Sign-in failed")
    if not verified:
        if (
            credential.last_failure_at is None
            or credential.last_failure_at <= instant - FAILURE_WINDOW
        ):
            credential.failed_attempts = 0
        credential.failed_attempts += 1
        credential.last_failure_at = instant
        if credential.failed_attempts >= 5:
            credential.locked_until = instant + FAILURE_WINDOW
        db.commit()
        raise HTTPException(status_code=401, detail="Sign-in failed")
    credential.failed_attempts, credential.locked_until, credential.last_failure_at = (
        0,
        None,
        None,
    )
    if PASSWORD_HASHER.check_needs_rehash(encoded):
        credential.password_hash = PASSWORD_HASHER.hash(password)
    return credential


def issue_session(
    db: Session, user_id: str, response: Response, previous: str | None = None
) -> str:
    raw = secrets.token_urlsafe(32)
    csrf_token(raw)  # Reject incomplete configuration before creating a session.
    instant = now()
    if previous:
        db.query(LocalSession).filter_by(token_hash=digest(previous)).delete()
    db.query(LocalSession).filter(LocalSession.expires_at <= instant).delete()
    db.add(
        LocalSession(
            token_hash=digest(raw),
            user_id=user_id,
            created_at=instant,
            last_seen_at=instant,
            expires_at=instant + SESSION_LIFETIME,
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        raw,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=int(SESSION_LIFETIME.total_seconds()),
    )
    response.headers["Cache-Control"] = "no-store"
    return raw


def resolve_session(request: Request, db: Session) -> dict[str, str]:
    if "local" not in auth_methods():
        raise HTTPException(status_code=401, detail="Unauthorized")
    check_transport(request, write=request.method not in {"GET", "HEAD", "OPTIONS"})
    raw = request.cookies.get(COOKIE_NAME, "")
    if not raw or len(raw) > 128:
        raise HTTPException(status_code=401, detail="Unauthorized")
    session = db.query(LocalSession).filter_by(token_hash=digest(raw)).first()
    instant = now()
    if (
        session is None
        or session.expires_at <= instant
        or session.last_seen_at <= instant - IDLE_LIFETIME
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("x-csrf-token", "")
        if not re.fullmatch(r"[0-9a-f]{64}", supplied) or not hmac.compare_digest(
            supplied, csrf_token(raw)
        ):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
    user = db.get(User, session.user_id)
    if user is None or db.get(LocalCredential, session.user_id) is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if session.last_seen_at <= instant - timedelta(minutes=1):
        session.last_seen_at = instant
        try:
            db.commit()
        except StaleDataError:
            # Logout/recovery may delete this row after the request read it.
            db.rollback()
            raise HTTPException(status_code=401, detail="Unauthorized") from None
    return {
        "github_id": user.github_id,
        "username": user.username,
        "email": user.email,
        "scope": "full",
        "auth_method": "local",
    }
