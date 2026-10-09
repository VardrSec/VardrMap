"""Remediation notes and completed retest attempts, retained as a finding timeline."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import finding_history
from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import Evidence, Finding, FindingActivity
from security import strip_html

router = APIRouter()


class ActivityCreate(BaseModel):
    kind: Literal["remediation", "retest"]
    notes: str = Field(min_length=1, max_length=10000)
    outcome: Literal["still_open", "partially_fixed", "verified_fixed", "inconclusive"] | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


def _finding(db, program_id, finding_id, lock=False):
    query = db.query(Finding).filter(Finding.program_id == program_id, Finding.id == finding_id)
    row = query.with_for_update().first() if lock else query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return row


@router.get("/engagements/{program_id}/findings/{finding_id}/activity")
def list_activity(program_id: str, finding_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    get_engagement_or_404(program_id, current_user, db)
    _finding(db, program_id, finding_id)
    query = db.query(FindingActivity).filter(FindingActivity.program_id == program_id, FindingActivity.finding_id == finding_id)
    total = query.count()
    rows = query.order_by(FindingActivity.created_at.desc(), FindingActivity.id).offset(offset).limit(limit).all()
    return {"activities": [finding_history.serialize(r) for r in rows], "total": total, "offset": offset, "limit": limit}


@router.post("/engagements/{program_id}/findings/{finding_id}/activity", status_code=201)
def add_activity(program_id: str, finding_id: str, body: ActivityCreate, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    finding = _finding(db, program_id, finding_id, lock=True)
    if (body.kind == "retest") != (body.outcome is not None):
        raise HTTPException(status_code=400, detail="A retest requires an outcome; remediation notes do not take one")
    notes = strip_html(body.notes).strip()
    if not notes:
        raise HTTPException(status_code=400, detail="Notes are required")
    ids = set(body.evidence_ids)
    evidence = db.query(Evidence).filter(Evidence.program_id == program_id, Evidence.finding_id == finding_id, Evidence.id.in_(ids)).all() if ids else []
    if len(evidence) != len(ids):
        raise HTTPException(status_code=404, detail="Evidence not found on this finding")
    finding_history.capture_baseline(db, finding, current_user["github_id"])
    # Keep evidence identity and integrity even if retention later removes its body.
    references = [{"id": e.id, "title": e.title, "content_hash": e.content_hash} for e in evidence]
    entry = finding_history.record(db, finding, current_user["github_id"], body.kind, notes, body.outcome, references)
    db.flush()
    log_action(db, current_user["github_id"], "create", "finding_activity", entry.id, program_id)
    db.commit()
    db.refresh(entry)
    return finding_history.serialize(entry)
