from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from limiter import limiter
from models import JobEvent, ScanJob

router = APIRouter(tags=["jobs"])


EventKind = Literal["started", "targets_resolved", "running", "uploaded", "done", "failed", "log"]


class EventCreate(BaseModel):
    kind: EventKind
    text: str = Field(default="", max_length=2000)


_VALID_TOOLS = {"httpx", "nuclei", "subfinder", "nmap"}
_VALID_SOURCES = {"scope", "recon"}

# Per-tool allowed config keys. Keys not in this set are rejected.
_TOOL_CONFIG_KEYS: dict[str, set[str]] = {
    "httpx":     {"status_code", "limit"},
    "nuclei":    {"severity", "templates"},
    "subfinder": {"recursive", "sources"},
    "nmap":      {"top_ports", "timing"},
}
_NUCLEI_SEVERITIES = {"info", "low", "medium", "high", "critical"}


def _validate_job_config(tool_type: str, config: dict) -> None:
    allowed = _TOOL_CONFIG_KEYS.get(tool_type, set())
    unknown = set(config.keys()) - allowed
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown config keys for {tool_type}: {sorted(unknown)}",
        )
    if tool_type == "httpx" and "limit" in config:
        try:
            int(config["limit"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="httpx config.limit must be an integer")
    if tool_type == "nuclei" and config.get("severity"):
        parts = [s.strip() for s in str(config["severity"]).split(",") if s.strip()]
        bad = [s for s in parts if s not in _NUCLEI_SEVERITIES]
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"nuclei severity must be info/low/medium/high/critical, got: {bad}",
            )
    if tool_type == "nmap" and "timing" in config:
        try:
            t = int(config["timing"])
            if not (0 <= t <= 4):
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="nmap config.timing must be 0-4")


class JobCreate(BaseModel):
    tool_type: str              # "httpx", "nuclei", "subfinder", or "nmap"
    target_source: str          # "scope" or "recon"
    config: Optional[dict] = None


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
    if body.tool_type not in _VALID_TOOLS:
        raise HTTPException(status_code=400, detail=f"tool_type must be one of {sorted(_VALID_TOOLS)}")
    if body.target_source not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail="target_source must be scope or recon")
    if body.config:
        _validate_job_config(body.tool_type, body.config)

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


@router.post("/jobs/{job_id}/claim")
def claim_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Atomically claim a pending job. Returns 409 if the job is not in 'pending' state."""
    job = (
        db.query(ScanJob)
        .filter(ScanJob.id == job_id, ScanJob.owner_github_id == current_user["github_id"])
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)
    if job.status != "pending":
        raise HTTPException(status_code=409, detail=f"job is already {job.status}")
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return serialize_job(job)


def serialize_event(e: JobEvent) -> dict:
    return {
        "id":             e.id,
        "job_id":         e.job_id,
        "kind":           e.kind,
        "text":           e.text,
        "created_at":     e.created_at.isoformat() if e.created_at else None,
    }


@router.post("/jobs/{job_id}/events", status_code=201)
@limiter.limit("600/minute")
def create_job_event(
    request: Request,
    job_id: str,
    body: EventCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """VardrRunner posts lifecycle events here while executing a job."""
    job = (
        db.query(ScanJob)
        .filter(ScanJob.id == job_id, ScanJob.owner_github_id == current_user["github_id"])
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)

    event = JobEvent(
        job_id=job_id,
        owner_github_id=current_user["github_id"],
        kind=body.kind,
        text=body.text,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return serialize_event(event)


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete a job and its events. Useful for removing stuck jobs."""
    job = (
        db.query(ScanJob)
        .filter(ScanJob.id == job_id, ScanJob.owner_github_id == current_user["github_id"])
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)
    log_action(db, current_user["github_id"], "delete", "scan_job", job_id, job.program_id)
    db.delete(job)
    db.commit()
    return {"message": "Job deleted"}


@router.get("/jobs/{job_id}/events")
def get_job_events(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Frontend polls this to stream job lifecycle events into the Terminal."""
    job = (
        db.query(ScanJob)
        .filter(ScanJob.id == job_id, ScanJob.owner_github_id == current_user["github_id"])
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)

    events = (
        db.query(JobEvent)
        .filter(JobEvent.job_id == job_id)
        .order_by(JobEvent.created_at.asc())
        .all()
    )
    return {"events": [serialize_event(e) for e in events]}
