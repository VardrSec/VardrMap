import hashlib
import os
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from db import get_db
from models import (
    ApiKey,
    AuditLog,
    Engagement,
    EngagementMember,
    Organization,
    OrganizationMember,
    User,
)

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


ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def personal_org(github_id: str, db: Session) -> Organization:
    """The caller's personal organization, created on first use.

    Every user has one so single-operator use never has to think about orgs.
    Created lazily rather than at signup because users predate this table.
    """
    org = (
        db.query(Organization)
        .filter(Organization.personal_for_github_id == github_id)
        .first()
    )
    if org:
        return org
    org = Organization(name=f"{github_id}'s workspace", personal_for_github_id=github_id)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(org_id=org.id, github_id=github_id, role="owner"))
    db.flush()
    return org


def org_role(org_id: str | None, github_id: str, db: Session) -> str | None:
    """The caller's role in an org, or None if they are not a member."""
    if not org_id:
        return None
    row = (
        db.query(OrganizationMember.role)
        .filter(OrganizationMember.org_id == org_id, OrganizationMember.github_id == github_id)
        .first()
    )
    return row[0] if row else None


def engagement_access(engagement: Engagement, github_id: str, db: Session) -> str | None:
    """Effective role on an engagement, or None when there is no access.

    Three grants are honoured, highest wins:
      1. Direct ownership — the legacy anchor, still authoritative.
      2. Organization membership — the new tenancy path.
      3. Per-engagement invitation — how collaboration worked before orgs.

    All three coexist deliberately. Dropping (1) or (3) on the same commit that
    introduces (2) would revoke access for every existing user the moment the
    migration lands.
    """
    if engagement.owner_github_id == github_id:
        return "owner"

    roles = []
    role = org_role(engagement.org_id, github_id, db)
    if role:
        roles.append(role)

    member = (
        db.query(EngagementMember.role)
        .filter(
            EngagementMember.program_id == engagement.id,
            EngagementMember.member_github_id == github_id,
        )
        .first()
    )
    if member:
        roles.append(member[0] or "member")

    if not roles:
        return None
    return max(roles, key=lambda r: ROLE_RANK.get(r, 0))


def get_engagement_or_404(program_id: str, current_user: dict[str, str], db: Session) -> Engagement:
    """Return engagement if the caller has any access. 404 in all other cases.

    404 rather than 403 is deliberate: a non-member must not be able to learn
    that another tenant's engagement exists.
    """
    engagement = db.query(Engagement).filter(Engagement.id == program_id).first()
    if not engagement:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if engagement_access(engagement, current_user["github_id"], db) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return engagement


def accessible_org_ids(github_id: str, db: Session) -> list[str]:
    """Every organization the caller belongs to, plus their personal one."""
    ids = [
        r[0] for r in db.query(OrganizationMember.org_id)
        .filter(OrganizationMember.github_id == github_id).all()
    ]
    personal = (
        db.query(Organization.id)
        .filter(Organization.personal_for_github_id == github_id)
        .first()
    )
    if personal and personal[0] not in ids:
        ids.append(personal[0])
    return ids


def accessible_engagement_ids(github_id: str, db: Session) -> list[str]:
    """Every engagement id the caller can reach, by any of the three grants.

    Used by list endpoints that previously filtered on owner_github_id and so
    hid an engagement's jobs from a teammate who could see its findings.
    """
    owned = [r[0] for r in db.query(Engagement.id).filter(Engagement.owner_github_id == github_id).all()]

    org_ids = [
        r[0] for r in db.query(OrganizationMember.org_id)
        .filter(OrganizationMember.github_id == github_id).all()
    ]
    via_org = (
        [r[0] for r in db.query(Engagement.id).filter(Engagement.org_id.in_(org_ids)).all()]
        if org_ids else []
    )

    invited = [
        r[0] for r in db.query(EngagementMember.program_id)
        .filter(EngagementMember.member_github_id == github_id).all()
    ]

    seen: set[str] = set()
    return [x for x in owned + via_org + invited if not (x in seen or seen.add(x))]


def require_engagement_owner(engagement: Engagement, current_user: dict[str, str]) -> None:
    """Raise 403 when a member (non-owner) attempts a write that requires ownership.
    Call after get_engagement_or_404 so the engagement is already verified accessible."""
    if engagement.owner_github_id != current_user["github_id"]:
        raise HTTPException(status_code=403, detail="This action requires engagement ownership")


def require_member_write(engagement: Engagement, current_user: dict, db: Session) -> None:
    """Raise 403 if the current user is a viewer-role member.
    Call after get_engagement_or_404. Owners always pass."""
    if engagement_access(engagement, current_user["github_id"], db) == "viewer":
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

    github_id = current_user["github_id"]
    org_ids = accessible_org_ids(github_id, db)
    owned = db.query(Client).filter(
        Client.id == client_id,
        (Client.owner_github_id == github_id)
        | (Client.org_id.in_(org_ids) if org_ids else False),
    ).first()
    if not owned:
        raise HTTPException(status_code=404, detail="Client not found")
    return owned.id
