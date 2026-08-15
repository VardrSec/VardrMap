from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from db import get_db
from deps import (
    accessible_engagement_ids,
    get_current_user,
    get_engagement_or_404,
    log_action,
    parse_iso_datetime,
    personal_org,
    require_engagement_owner,
    require_member_write,
    resolve_owned_client_id,
)
from models import Finding, ManualTest, Engagement, EngagementMember, ReconItem, Report, ScanItem, User
from schemas import EngagementCreate, EngagementUpdate
from security import strip_html
from serializers import serialize_engagement

router = APIRouter()


@router.post("/auth/sync")
def auth_sync(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if user:
        user.username = current_user["username"]
        user.email = current_user["email"]
    else:
        user = User(
            github_id=current_user["github_id"],
            username=current_user["username"],
            email=current_user["email"],
        )
        db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "github_id": user.github_id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }



@router.get("/engagements")
def get_programs(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    github_id = current_user["github_id"]
    # One source of truth for reachability: ownership, organization membership,
    # and per-engagement invitation. Listing only owned + invited engagements
    # hid every engagement a user could reach solely through their org.
    reachable = accessible_engagement_ids(github_id, db)
    all_engagements = (
        db.query(Engagement).filter(Engagement.id.in_(reachable)).all() if reachable else []
    )
    items = [serialize_engagement(p, db, github_id=github_id) for p in all_engagements]
    # Both keys carry the same list. "engagements" is the name going forward;
    # "programs" is kept because VardrRunner reads it (api.py: .get("programs"))
    # and ships from its own repository on its own schedule.
    return {"engagements": items, "programs": items}


@router.post("/engagements")
def create_engagement(
    payload: EngagementCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ensure user row exists before creating engagement (FK safety)
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if not user:
        user = User(
            github_id=current_user["github_id"],
            username=current_user["username"],
            email=current_user["email"],
        )
        db.add(user)
        db.flush()

    # Every engagement belongs to an organization from creation. Solo users get
    # a personal one they never have to think about; it only becomes visible
    # when someone is invited into it.
    org = personal_org(current_user["github_id"], db)

    engagement = Engagement(
        owner_github_id=current_user["github_id"],
        org_id=org.id,
        name=payload.name,
        platform=payload.platform or "",
        program_url=payload.program_url or "",
        scope_summary=payload.scope_summary or "",
        severity_guidance=payload.severity_guidance or "",
        safe_harbor_notes=payload.safe_harbor_notes or "",
        client_id=resolve_owned_client_id(payload.client_id, current_user, db),
        engagement_type=payload.engagement_type,
        engagement_status=payload.engagement_status,
        starts_at=parse_iso_datetime(payload.starts_at, "starts_at"),
        ends_at=parse_iso_datetime(payload.ends_at, "ends_at"),
    )
    db.add(engagement)
    db.flush()
    log_action(db, current_user["github_id"], "create", "engagement", engagement.id)
    db.commit()
    db.refresh(engagement)
    return serialize_engagement(engagement, db, github_id=current_user["github_id"])


@router.get("/engagements/{program_id}")
def get_engagement(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    return serialize_engagement(engagement, db, github_id=current_user["github_id"])


@router.patch("/engagements/{program_id}")
def update_engagement(
    program_id: str,
    payload: EngagementUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_engagement_owner(engagement, current_user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        # Dates arrive as strings and client_id must be proven owned; the rest
        # of the fields are plain values and pass through as before.
        if key in ("starts_at", "ends_at"):
            value = parse_iso_datetime(value, key)
        elif key == "client_id":
            value = resolve_owned_client_id(value, current_user, db)
        setattr(engagement, key, value)
    log_action(db, current_user["github_id"], "update", "engagement", program_id, program_id)
    db.commit()
    db.refresh(engagement)
    return serialize_engagement(engagement, db, github_id=current_user["github_id"])


@router.get("/engagements/{program_id}/stats")
def get_engagement_stats(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lightweight aggregate stats for an engagement — used by the Dashboard stat cards.
    Returns counts and breakdowns without serializing full objects."""
    get_engagement_or_404(program_id, current_user, db)

    def count(model, extra_filter=None):
        q = db.query(func.count(model.id)).filter(model.program_id == program_id)  # type: ignore[attr-defined]
        if extra_filter is not None:
            q = q.filter(extra_filter)
        return q.scalar() or 0

    sev_rows = (
        db.query(Finding.severity, func.count(Finding.id))
        .filter(Finding.program_id == program_id)
        .group_by(Finding.severity)
        .all()
    )

    return {
        "recon_count":          count(ReconItem),
        "scans_count":          count(ScanItem),
        "findings_count":       count(Finding),
        "manual_tests_count":   count(ManualTest),
        "reports_count":        count(Report),
        "findings_by_severity": {sev: cnt for sev, cnt in sev_rows},
    }


@router.delete("/engagements/{program_id}")
def delete_engagement(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_engagement_owner(engagement, current_user)
    log_action(db, current_user["github_id"], "delete", "engagement", program_id)
    db.delete(engagement)
    db.commit()
    return {"message": "Engagement deleted"}


class StopWorkRequest(BaseModel):
    reason: str = Field(default="", max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def sanitize(cls, v):
        return strip_html(v) if v else ""


@router.post("/engagements/{program_id}/stop-work")
def engage_stop_work(
    program_id: str,
    body: StopWorkRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Engage the emergency brake. Every execution for this engagement is denied
    until it is released — regardless of scope, window, or authorization.

    Deliberately idempotent: re-engaging an already-stopped engagement succeeds
    rather than erroring. During an incident the operator needs certainty that
    the brake is on, not an argument about whether they pulled it twice.
    """
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)

    if engagement.stop_work_at is None:
        engagement.stop_work_at = datetime.now(timezone.utc)
    engagement.stop_work_reason = body.reason
    log_action(db, current_user["github_id"], "stop_work", "engagement", program_id, program_id)
    db.commit()
    db.refresh(engagement)
    return serialize_engagement(engagement, db)


@router.delete("/engagements/{program_id}/stop-work")
def release_stop_work(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Release the emergency brake. Only the engagement owner may do this —
    engaging a stop is a safety action anyone on the engagement should be able
    to take; lifting one is an authorization decision."""
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_engagement_owner(engagement, current_user)

    engagement.stop_work_at = None
    engagement.stop_work_reason = ""
    log_action(db, current_user["github_id"], "resume_work", "engagement", program_id, program_id)
    db.commit()
    db.refresh(engagement)
    return serialize_engagement(engagement, db)
