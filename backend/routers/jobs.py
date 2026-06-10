import json
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import SessionLocal, get_db
from deps import get_current_user, get_program_or_404, log_action
from models import JobLog, ScanJob

router = APIRouter(tags=["jobs"])


class JobCreate(BaseModel):
    tool_type: str              # "httpx", "nuclei", or "subfinder"
    target_source: str          # "scope" or "recon"
    config: Optional[dict] = None  # {status_code, limit, severity, templates, recursive, sources}


class JobStatusUpdate(BaseModel):
    status: str                          # "running" | "done" | "failed"
    error_message: Optional[str] = None


class LogLineIn(BaseModel):
    kind: str = "out"   # sys|info|out|ok|warn|err|hit
    text: str


class LogBatch(BaseModel):
    lines: list[LogLineIn]


_VALID_KINDS = {"sys", "info", "out", "ok", "warn", "err", "hit"}


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


@router.post("/jobs/{job_id}/logs")
def append_logs(
    job_id: str,
    body: LogBatch,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Append log lines to a job. Called by VardrRunner as the tool produces output."""
    job = (
        db.query(ScanJob)
        .filter(ScanJob.id == job_id, ScanJob.owner_github_id == current_user["github_id"])
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)

    for line in body.lines:
        kind = line.kind if line.kind in _VALID_KINDS else "out"
        db.add(JobLog(job_id=job_id, kind=kind, text=line.text[:4096]))
    db.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/logs/stream")
def stream_job_logs(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE endpoint: streams log lines as they're written by VardrRunner.
    Polls every second; closes ~2 s after the job reaches done/failed."""
    job = (
        db.query(ScanJob)
        .filter(ScanJob.id == job_id, ScanJob.owner_github_id == current_user["github_id"])
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)

    def event_stream():
        stream_db = SessionLocal()
        try:
            cursor = 0       # last job_log.id seen
            drain_polls = 0  # idle polls after job terminal state
            MAX_DRAIN = 2

            while True:
                stream_db.expire_all()
                new_logs = (
                    stream_db.query(JobLog)
                    .filter(JobLog.job_id == job_id, JobLog.id > cursor)
                    .order_by(JobLog.id)
                    .all()
                )
                for log in new_logs:
                    cursor = log.id
                    yield f"data: {json.dumps({'kind': log.kind, 'text': log.text})}\n\n"

                if new_logs:
                    drain_polls = 0
                else:
                    job_now = stream_db.query(ScanJob).filter(ScanJob.id == job_id).first()
                    if job_now and job_now.status in ("done", "failed"):
                        drain_polls += 1
                        if drain_polls >= MAX_DRAIN:
                            yield "event: done\ndata: {}\n\n"
                            break

                time.sleep(1)
        finally:
            stream_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
