"""Evidence attached to findings. Redacted on write, never on render."""
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import redaction
from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import Evidence, Finding
from security import sanitize_identifier, strip_html

router = APIRouter(tags=["evidence"])

KINDS = {"http_request", "http_response", "terminal_output", "tool_result", "note", "screenshot"}
SENSITIVITIES = {"public", "internal", "confidential", "restricted"}
RETENTIONS = {"engagement", "90d", "permanent"}

# Bounded so a pasted 50MB response cannot exhaust the row or the response.
MAX_BODY_CHARS = 200_000


class EvidenceCreate(BaseModel):
    kind: str = Field(default="note")
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=MAX_BODY_CHARS)
    finding_id: str | None = Field(default=None, max_length=100)
    collector: str = Field(default="", max_length=100)
    source: str = Field(default="", max_length=60)
    sensitivity: str = Field(default="internal")
    retention: str = Field(default="engagement")

    @field_validator("title", "collector", "source", mode="before")
    @classmethod
    def clean_short(cls, v):
        return sanitize_identifier(v) if v else ""


class EvidenceLink(BaseModel):
    finding_id: str = Field(min_length=1, max_length=100)


@router.post("/engagements/{program_id}/evidence/{evidence_id}/link")
def link_evidence(
    program_id: str,
    evidence_id: str,
    payload: EvidenceLink,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly associate existing evidence with a finding, without copying it."""
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    finding = db.query(Finding).filter(
        Finding.id == payload.finding_id, Finding.program_id == program_id
    ).with_for_update().first()
    item = db.query(Evidence).filter(
        Evidence.id == evidence_id, Evidence.program_id == program_id
    ).with_for_update().first()
    if finding is None or item is None:
        raise HTTPException(status_code=404, detail="Finding or evidence not found")
    if item.finding_id and item.finding_id != finding.id:
        raise HTTPException(status_code=409, detail="Evidence is already linked to another finding")
    if not item.finding_id:
        # Atomic condition also prevents competing links on databases without
        # row locks. Never move evidence out of an existing finding's history.
        changed = db.query(Evidence).filter(
            Evidence.id == item.id, Evidence.program_id == program_id,
            Evidence.finding_id.is_(None),
        ).update({Evidence.finding_id: finding.id}, synchronize_session=False)
        if not changed:
            raise HTTPException(status_code=409, detail="Evidence link changed; reload and retry")
        log_action(db, current_user["github_id"], "link", "evidence", item.id, program_id)
        db.commit()
        db.refresh(item)
    return _serialize(item)


def _serialize(e: Evidence) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "title": e.title or "",
        "body": e.body or "",
        "content_hash": e.content_hash or "",
        "finding_id": e.finding_id or "",
        "collector": e.collector or "",
        "source": e.source or "",
        "job_id": e.job_id,
        "case_id": e.case_id,
        "case_ref": e.case_ref,
        "identity_id": e.identity_id,
        "observed_outcome": e.observed_outcome,
        "expected_decision": e.expected_decision,
        "sensitivity": e.sensitivity or "internal",
        "retention": e.retention or "engagement",
        "redacted": bool(e.redacted),
        "created_at": e.created_at.isoformat() if e.created_at else "",
    }


@router.post("/engagements/{program_id}/evidence", status_code=201)
def create_evidence(
    program_id: str,
    payload: EvidenceCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)

    if payload.kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(KINDS)}")
    if payload.sensitivity not in SENSITIVITIES:
        raise HTTPException(
            status_code=400, detail=f"sensitivity must be one of {sorted(SENSITIVITIES)}"
        )
    if payload.retention not in RETENTIONS:
        raise HTTPException(
            status_code=400, detail=f"retention must be one of {sorted(RETENTIONS)}"
        )

    if payload.finding_id:
        owns = (
            db.query(Finding)
            .filter(Finding.id == payload.finding_id, Finding.program_id == program_id)
            .first()
        )
        if not owns:
            raise HTTPException(status_code=400, detail="finding_id must belong to this engagement")

    # The single point where evidence text is accepted. Redact here so no
    # downstream path — log, export, error, debug endpoint — can leak what was
    # never stored. A note is prose, so it keeps HTML stripping too.
    body = redaction.redact_text(payload.body)
    if payload.kind == "note":
        body = strip_html(body)

    item = Evidence(
        program_id=program_id,
        finding_id=payload.finding_id or None,
        kind=payload.kind,
        title=payload.title,
        body=body,
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        collector=payload.collector or current_user["github_id"],
        source=payload.source,
        sensitivity=payload.sensitivity,
        retention=payload.retention,
        redacted=True,
    )
    db.add(item)
    db.flush()
    log_action(db, current_user["github_id"], "create", "evidence", item.id, program_id)
    db.commit()
    db.refresh(item)
    return _serialize(item)


@router.get("/engagements/{program_id}/evidence")
def list_evidence(
    program_id: str,
    finding_id: str | None = Query(default=None),
    job_id: str | None = Query(default=None, max_length=200),
    case_id: str | None = Query(default=None, max_length=200),
    identity_id: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    query = db.query(Evidence).filter(Evidence.program_id == program_id)
    if finding_id:
        query = query.filter(Evidence.finding_id == finding_id)
    for column, value in ((Evidence.job_id, job_id), (Evidence.case_id, case_id), (Evidence.identity_id, identity_id)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(Evidence.created_at.desc()).offset(offset).limit(limit).all()
    return {"evidence": [_serialize(e) for e in rows], "total": total}


@router.delete("/engagements/{program_id}/evidence/{evidence_id}")
def delete_evidence(
    program_id: str,
    evidence_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    item = (
        db.query(Evidence)
        .filter(Evidence.id == evidence_id, Evidence.program_id == program_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Evidence not found")
    db.delete(item)
    log_action(db, current_user["github_id"], "delete", "evidence", evidence_id, program_id)
    db.commit()
    return {"message": "Evidence deleted"}
