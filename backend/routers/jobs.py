from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from models import ScanJob

router = APIRouter(tags=["jobs"])


class JobCreate(BaseModel):
    tool_type: str              # "httpx", "nuclei", or "subfinder"
    target_source: str          # "scope" or "recon"
    config: Optional[dict] = None  # {status_code, limit, severity, templates, recursive, sources}


class JobStatusUpdate(BaseModel):
    status: str                          # "running" | "done" | "failed"
    error_message: Optional[str] = None


def serialize_job(j: ScanJob) -> dict:
    return {
        "id": j.id,
        "program_id": j.program_id,
        "tool_type": j.tool_type,
        "target_source": j.target_source,
        "config": j.config or {},
        "status": j.status,
        "created_at":   j.created_at.isoformat()   if j.created_at   else None,
        "started_at":   j.started_at.isoformat()   if j.started_at   else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "error_message": j.error_message or "",
    }


@router.post("/programs/{program_id}/jobs")
def create_job(
    program_id: str,
    body: JobCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    if body.tool_type not in ("httpx", "nuclei", "subfinder"):
        raise HTTPException(status_code=400, detail="tool_type must be httpx, nuclei, or subfinder")
    if body.target_source not in ("scope", "recon"):
        raise HTTPException(status_code=400, detail="target_source must be scope or recon")

    job = ScanJob(
        program_id=program_id,
        owner_github_id=current_user["github_id"],
        tool_type=body.tool_type,
        target_source=body.target_source,
        config=body.config or {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    log_action(db, current_user["github_id"], "create", "scan_job", job.id, program_id)
    db.commit()
    return serialize_job(job)


@router.get("/programs/{program_id}/jobs")
def list_jobs(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    jobs = (
        db.query(ScanJob)
        .filter(ScanJob.program_id == program_id)
        .order_by(ScanJob.created_at.desc())
        .all()
    )
    return {"jobs": [serialize_job(j) for j in jobs]}


@router.get("/jobs/pending")
def get_pending_jobs(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """All pending jobs for the authenticated user, oldest first. Used by VardrRunner to poll."""
    jobs = (
        db.query(ScanJob)
        .filter(
            ScanJob.owner_github_id == current_user["github_id"],
            ScanJob.status == "pending",
        )
        .order_by(ScanJob.created_at.asc())
        .all()
    )
    return {"jobs": [serialize_job(j) for j in jobs]}


@router.patch("/jobs/{job_id}")
def update_job(
    job_id: str,
    body: JobStatusUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update job status. VardrRunner uses this to claim (running) and complete (done/failed) jobs."""
    job = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.owner_github_id == current_user["github_id"],
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)

    valid = ("pending", "running", "done", "failed")
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")

    job.status = body.status
    if body.status == "running" and not job.started_at:
        job.started_at = datetime.now(timezone.utc)
    if body.status in ("done", "failed"):
        job.completed_at = datetime.now(timezone.utc)
    if body.error_message is not None:
        job.error_message = body.error_message

    db.commit()
    db.refresh(job)
    return serialize_job(job)
