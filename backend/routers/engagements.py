from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from db import get_db
from deps import (
    get_current_user,
    get_engagement_or_404,
    log_action,
    parse_iso_datetime,
    require_engagement_owner,
    resolve_owned_client_id,
)
from models import Finding, ManualTest, Engagement, EngagementMember, ReconItem, Report, ScanItem, Submission, User
from schemas import EngagementCreate, EngagementUpdate
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
    owned = db.query(Engagement).filter(Engagement.owner_github_id == github_id).all()

    # Also include programs where this user is an invited member
    member_engagement_ids = [
        row[0]
        for row in db.query(EngagementMember.program_id).filter(
            EngagementMember.member_github_id == github_id
        ).all()
    ]
    shared = (
        db.query(Engagement)
        .filter(Engagement.id.in_(member_engagement_ids))
        .all()
        if member_engagement_ids else []
    )

    seen = {p.id for p in owned}
    all_engagements = owned + [p for p in shared if p.id not in seen]
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

    engagement = Engagement(
        owner_github_id=current_user["github_id"],
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
    """Lightweight aggregate stats for a engagement — used by the Dashboard stat cards.
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

    sub_status_rows = (
        db.query(Submission.status, func.count(Submission.id))
        .filter(Submission.program_id == program_id)
        .group_by(Submission.status)
        .all()
    )

    return {
        "recon_count":          count(ReconItem),
        "scans_count":          count(ScanItem),
        "findings_count":       count(Finding),
        "manual_tests_count":   count(ManualTest),
        "reports_count":        count(Report),
        "submissions_count":    count(Submission),
        "findings_by_severity": {sev: cnt for sev, cnt in sev_rows},
        "submissions_by_status": {status: cnt for status, cnt in sub_status_rows},
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
