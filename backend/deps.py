import hashlib
import os
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from db import get_db
from models import ApiKey, AuditLog, Engagement, EngagementMember, User

BACKEND_JWT_SECRET = os.getenv("BACKEND_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
_API_KEY_PREFIX = "vmap_"


# Auth flow: two accepted token types on the Authorization header.
#
# 1. Browser JWT — minted by NextAuth after GitHub OAuth, short-lived (1h),
#    verified against BACKEND_JWT_SECRET with aud/iss checks.
#
# 2. Personal API key — opaque token starting with "vmap_", stored as
#    SHA-256 hash in api_keys table. Used by external tools (e.g. Burp).
#    The plaintext token is shown once at generation; only the hash is kept.
def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not BACKEND_JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server auth not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    if token.startswith(_API_KEY_PREFIX):
        return _resolve_api_key(token, db)
    return _resolve_jwt(token)


def _resolve_api_key(token: str, db: Session) -> dict[str, str]:
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    api_key.last_used_at = datetime.now(timezone.utc)
    db.commit()
    user = db.query(User).filter(User.github_id == api_key.github_id).first()
    return {
        "github_id": api_key.github_id,
        "username":  user.username if user else "",
        "email":     user.email    if user else "",
        "scope":     api_key.scope or "full",
    }


def _resolve_jwt(token: str) -> dict[str, str]:
    try:
        payload = jwt.decode(
            token,
            BACKEND_JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience="vardrmap-backend",
            issuer="vardrmap-frontend",
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Unauthorized")
    github_id = payload.get("sub")
    if not github_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "github_id": str(github_id),
        "username":  str(payload.get("username", "")),
        "email":     str(payload.get("email", "")),
        "scope":     "full",  # browser JWTs always have full access
    }


def get_engagement_or_404(program_id: str, current_user: dict[str, str], db: Session) -> Engagement:
    """Return engagement if the user is the owner or an invited member. 404 in all other cases."""
    engagement = db.query(Engagement).filter(Engagement.id == program_id).first()
    if not engagement:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if engagement.owner_github_id == current_user["github_id"]:
        return engagement
    member = db.query(EngagementMember).filter(
        EngagementMember.program_id == program_id,
        EngagementMember.member_github_id == current_user["github_id"],
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return engagement


def require_engagement_owner(engagement: Engagement, current_user: dict[str, str]) -> None:
    """Raise 403 when a member (non-owner) attempts a write that requires ownership.
    Call after get_engagement_or_404 so the engagement is already verified accessible."""
    if engagement.owner_github_id != current_user["github_id"]:
        raise HTTPException(status_code=403, detail="This action requires engagement ownership")


def require_member_write(engagement: Engagement, current_user: dict, db: Session) -> None:
    """Raise 403 if the current user is a viewer-role member.
    Call after get_engagement_or_404. Owners always pass."""
    if engagement.owner_github_id == current_user["github_id"]:
        return
    member = db.query(EngagementMember).filter(
        EngagementMember.program_id == engagement.id,
        EngagementMember.member_github_id == current_user["github_id"],
    ).first()
    if member and member.role == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot make changes to this engagement")


def require_full_scope(
    current_user: dict[str, str] = Depends(get_current_user),
) -> dict[str, str]:
    """Dependency that blocks runner-scoped API keys from non-runner endpoints."""
    if current_user.get("scope") == "runner":
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires a full-access API key (scope=full)",
        )
    return current_user


def log_action(
    db: Session,
    github_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    program_id: str | None = None,
) -> None:
    """Append an audit log entry. Caller is responsible for committing the session."""
    db.add(AuditLog(
        github_id=github_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        program_id=program_id or "",
    ))


def parse_iso_datetime(value: str | None, field: str) -> datetime | None:
    """Accept an ISO-8601 string, including a trailing Z, or None.

    Datetimes cross this API as strings, matching how they are serialised on
    the way out. Parsing here keeps string values from being written straight
    into DateTime columns by a bulk setattr loop.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be an ISO-8601 datetime, e.g. 2026-08-04T09:00:00Z",
        )


def resolve_owned_client_id(client_id: str | None, current_user: dict[str, str], db: Session) -> str | None:
    """Validate that a client belongs to the caller before linking an engagement to it.

    Without this check the field would be an existence oracle: attaching a
    engagement to another user's client id would either succeed or fail
    differently, revealing whether that id exists.
    """
    if not client_id:
        return None
    from models import Client  # local import; models imports nothing from deps

    owned = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_github_id == current_user["github_id"],
    ).first()
    if not owned:
        raise HTTPException(status_code=404, detail="Client not found")
    return owned.id
