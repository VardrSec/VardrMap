import os

from fastapi import Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from models import AuditLog, Program

BACKEND_JWT_SECRET = os.getenv("BACKEND_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"


# Auth flow: GitHub OAuth is handled entirely by NextAuth on the frontend.
# After sign-in, NextAuth mints a short-lived JWT (signed with BACKEND_JWT_SECRET)
# that includes the GitHub user's ID, username, and email. Every request carries
# that token in the Authorization header, and this function verifies it.
# The backend never talks to GitHub directly.
def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not BACKEND_JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server auth not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ", 1)[1].strip()
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
        "username": str(payload.get("username", "")),
        "email": str(payload.get("email", "")),
    }


def get_program_or_404(program_id: str, current_user: dict[str, str], db: Session) -> Program:
    program = (
        db.query(Program)
        .filter(
            Program.id == program_id,
            Program.owner_github_id == current_user["github_id"],
        )
        .first()
    )
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    return program


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
