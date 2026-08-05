"""Authorizations — the record of permission to test a engagement.

Access is scoped through the engagement, so owners and invited members can read
the authorisation covering work they are doing, and everyone else gets 404.

Authorisations are append-mostly on purpose. Superseding one creates a new row
and marks the old `expired` rather than editing history in place: the value of
this record is being able to say later what was permitted at the time, and an
edited row cannot answer that.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import (
    get_current_user,
    get_engagement_or_404,
    log_action,
    parse_iso_datetime,
    require_member_write,
)
from models import Authorization
from schemas import AuthorizationCreate, AuthorizationUpdate
from serializers import serialize_authorization

router = APIRouter()

_DATE_FIELDS = ("authorized_at", "window_start", "window_end")


def _get_authorization_or_404(
    program_id: str, authorization_id: str, current_user: dict[str, str], db: Session
) -> Authorization:
    # Engagement access is checked first, so a bad engagement id fails before the
    # authorisation is ever looked up.
    get_engagement_or_404(program_id, current_user, db)
    auth = db.query(Authorization).filter(
        Authorization.id == authorization_id,
        Authorization.program_id == program_id,
    ).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorization not found")
    return auth


@router.get("/engagements/{program_id}/authorizations")
def list_authorizations(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    items = db.query(Authorization).filter(
        Authorization.program_id == program_id,
    ).order_by(Authorization.created_at.desc()).all()
    return [serialize_authorization(a) for a in items]


@router.post("/engagements/{program_id}/authorizations", status_code=201)
def create_authorization(
    program_id: str,
    payload: AuthorizationCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)

    dates = {f: parse_iso_datetime(getattr(payload, f), f) for f in _DATE_FIELDS}

    auth = Authorization(
        program_id=program_id,
        owner_github_id=engagement.owner_github_id,
        permits=payload.permits or "",
        authorized_by=payload.authorized_by or "",
        reference=payload.reference or "",
        notes=payload.notes or "",
        status="active",
        **dates,
    )
    db.add(auth)
    db.flush()
    log_action(db, current_user["github_id"], "create", "authorization", auth.id, program_id)
    db.commit()
    db.refresh(auth)
    return serialize_authorization(auth)


@router.patch("/engagements/{program_id}/authorizations/{authorization_id}")
def update_authorization(
    program_id: str,
    authorization_id: str,
    payload: AuthorizationUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    auth = _get_authorization_or_404(program_id, authorization_id, current_user, db)

    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if field in _DATE_FIELDS:
            setattr(auth, field, parse_iso_datetime(value, field))
        else:
            setattr(auth, field, value)

    log_action(db, current_user["github_id"], "update", "authorization", auth.id, program_id)
    db.commit()
    db.refresh(auth)
    return serialize_authorization(auth)


@router.get("/engagements/{program_id}/authorization/active")
def get_active_authorization(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The authorisation currently permitting work, or null.

    This is the question the rest of the toolchain needs answered before it
    runs anything: is there permission right now? An authorisation counts when
    its status is active and the present moment falls inside its window. A
    missing window bound is treated as open on that side, which is normal for a
    bug bounty programme and unusual for an engagement.
    """
    get_engagement_or_404(program_id, current_user, db)
    now = datetime.now(timezone.utc)

    for auth in db.query(Authorization).filter(
        Authorization.program_id == program_id,
        Authorization.status == "active",
    ).order_by(Authorization.created_at.desc()).all():
        # Stored datetimes may be naive; compare on equal footing.
        start = auth.window_start
        end = auth.window_end
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start and now < start:
            continue
        if end and now > end:
            continue
        return serialize_authorization(auth)

    return None
