from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from models import Submission
from schemas import SubmissionCreate, SubmissionUpdate

router = APIRouter(tags=["submissions"])


def serialize(s: Submission) -> dict:
    return {
        "id":                 s.id,
        "program_id":         s.program_id,
        "finding_id":         s.finding_id or "",
        "report_id":          s.report_id or "",
        "platform":           s.platform or "",
        "platform_reference": s.platform_reference or "",
        "title":              s.title or "",
        "status":             s.status,
        "payout_usd":         s.payout_usd,
        "severity":           s.severity or "",
        "notes":              s.notes or "",
        "submitted_at":       s.submitted_at.isoformat()  if s.submitted_at  else None,
        "resolved_at":        s.resolved_at.isoformat()   if s.resolved_at   else None,
        "created_at":         s.created_at.isoformat()    if s.created_at    else None,
    }


@router.get("/programs/{program_id}/submissions")
def list_submissions(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    rows = (
        db.query(Submission)
        .filter(
            Submission.program_id == program_id,
            Submission.owner_github_id == current_user["github_id"],
        )
        .order_by(Submission.created_at.desc())
        .all()
    )
    return {"submissions": [serialize(s) for s in rows], "total": len(rows)}


@router.post("/programs/{program_id}/submissions")
def create_submission(
    program_id: str,
    body: SubmissionCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    sub = Submission(
        program_id=program_id,
        owner_github_id=current_user["github_id"],
        finding_id=body.finding_id or "",
        report_id=body.report_id or "",
        platform=body.platform or "",
        platform_reference=body.platform_reference or "",
        title=body.title,
        status=body.status,
        payout_usd=body.payout_usd,
        severity=body.severity or "",
        notes=body.notes or "",
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    log_action(db, current_user["github_id"], "create", "submission", sub.id, program_id)
    db.commit()
    return serialize(sub)


@router.patch("/programs/{program_id}/submissions/{submission_id}")
def update_submission(
    program_id: str,
    submission_id: str,
    body: SubmissionUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    sub = (
        db.query(Submission)
        .filter(
            Submission.id == submission_id,
            Submission.program_id == program_id,
            Submission.owner_github_id == current_user["github_id"],
        )
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404)

    for field in ("title", "platform", "platform_reference", "finding_id", "report_id",
                  "severity", "status", "payout_usd", "notes"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(sub, field, val)

    if body.resolved_at is not None:
        try:
            sub.resolved_at = datetime.fromisoformat(body.resolved_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="resolved_at must be an ISO 8601 datetime")

    # Auto-stamp resolved_at when transitioning to a terminal state
    terminal = {"accepted", "duplicate", "na", "paid", "rejected"}
    if body.status in terminal and sub.resolved_at is None:
        sub.resolved_at = datetime.now(timezone.utc)

    log_action(db, current_user["github_id"], "update", "submission", submission_id, program_id)
    db.commit()
    db.refresh(sub)
    return serialize(sub)


@router.delete("/programs/{program_id}/submissions/{submission_id}")
def delete_submission(
    program_id: str,
    submission_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    sub = (
        db.query(Submission)
        .filter(
            Submission.id == submission_id,
            Submission.program_id == program_id,
            Submission.owner_github_id == current_user["github_id"],
        )
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404)
    log_action(db, current_user["github_id"], "delete", "submission", submission_id, program_id)
    db.delete(sub)
    db.commit()
    return {"message": "Submission deleted"}
