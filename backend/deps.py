import hashlib
import os
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from db import get_db
from models import ApiKey, AuditLog, Program, ProgramMember, User

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


def get_program_or_404(program_id: str, current_user: dict[str, str], db: Session) -> Program:
    """Return program if the user is the owner or an invited member. 404 in all other cases."""
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    if program.owner_github_id == current_user["github_id"]:
        return program
    member = db.query(ProgramMember).filter(
        ProgramMember.program_id == program_id,
        ProgramMember.member_github_id == current_user["github_id"],
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Program not found")
    return program


def require_program_owner(program: Program, current_user: dict[str, str]) -> None:
    """Raise 403 when a member (non-owner) attempts a write that requires ownership.
    Call after get_program_or_404 so the program is already verified accessible."""
    if program.owner_github_id != current_user["github_id"]:
        raise HTTPException(status_code=403, detail="This action requires program ownership")


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
