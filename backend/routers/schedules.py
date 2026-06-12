"""
Scheduled scans — recurring scan definitions.

No backend cron: due schedules are materialized into pending scan_jobs when
VardrRunner polls GET /jobs/pending (see routers/jobs.py). The polling daemon
drives the clock, so schedules only fire while a runner is connected — which
is also the only time a job could execute anyway.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from models import ScheduledScan
from routers.jobs import _validate_job_config, _VALID_SOURCES, _VALID_TOOLS, SCHEDULE_INTERVALS as INTERVALS

router = APIRouter(tags=["schedules"])


class ScheduleCreate(BaseModel):
    tool_type: str
    target_source: str
    config: dict | None = None
    interval: str  # "hourly" | "daily" | "weekly"


class ScheduleUpdate(BaseModel):
    enabled: bool | None = None
    interval: str | None = None


def serialize_schedule(s: ScheduledScan) -> dict:
    return {
        "id":            s.id,
        "program_id":    s.program_id,
        "tool_type":     s.tool_type,
        "target_source": s.target_source,
        "config":        s.config or {},
        "interval":      s.interval,
        "enabled":       bool(s.enabled),
        "last_run_at":   s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at":   s.next_run_at.isoformat() if s.next_run_at else None,
        "created_at":    s.created_at.isoformat()  if s.created_at  else None,
    }


@router.get("/programs/{program_id}/schedules")
def list_schedules(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Use program.owner_github_id so members see the owner's schedules too
    program = get_program_or_404(program_id, current_user, db)
    rows = (
        db.query(ScheduledScan)
        .filter(
            ScheduledScan.program_id == program_id,
            ScheduledScan.owner_github_id == program.owner_github_id,
        )
        .order_by(ScheduledScan.created_at.desc())
        .all()
    )
    return {"schedules": [serialize_schedule(s) for s in rows], "total": len(rows)}


@router.post("/programs/{program_id}/schedules")
def create_schedule(
    program_id: str,
    body: ScheduleCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    if body.tool_type not in _VALID_TOOLS:
        raise HTTPException(status_code=400, detail=f"tool_type must be one of {sorted(_VALID_TOOLS)}")
    if body.target_source not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail="target_source must be scope or recon")
    if body.interval not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {sorted(INTERVALS)}")
    if body.config:
        _validate_job_config(body.tool_type, body.config)

    schedule = ScheduledScan(
        program_id=program_id,
        owner_github_id=program.owner_github_id,
        tool_type=body.tool_type,
        target_source=body.target_source,
        config=body.config or {},
        interval=body.interval,
        # Due immediately — the first job materializes on the runner's next poll
        next_run_at=datetime.now(timezone.utc),
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    log_action(db, current_user["github_id"], "create", "scheduled_scan", schedule.id, program_id)
    db.commit()
    return serialize_schedule(schedule)


@router.patch("/programs/{program_id}/schedules/{schedule_id}")
def update_schedule(
    program_id: str,
    schedule_id: str,
    body: ScheduleUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    schedule = (
        db.query(ScheduledScan)
        .filter(
            ScheduledScan.id == schedule_id,
            ScheduledScan.program_id == program_id,
            ScheduledScan.owner_github_id == program.owner_github_id,
        )
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404)

    if body.interval is not None:
        if body.interval not in INTERVALS:
            raise HTTPException(status_code=400, detail=f"interval must be one of {sorted(INTERVALS)}")
        schedule.interval = body.interval
    if body.enabled is not None:
        schedule.enabled = body.enabled

    log_action(db, current_user["github_id"], "update", "scheduled_scan", schedule_id, program_id)
    db.commit()
    db.refresh(schedule)
    return serialize_schedule(schedule)


@router.delete("/programs/{program_id}/schedules/{schedule_id}")
def delete_schedule(
    program_id: str,
    schedule_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    schedule = (
        db.query(ScheduledScan)
        .filter(
            ScheduledScan.id == schedule_id,
            ScheduledScan.program_id == program_id,
            ScheduledScan.owner_github_id == program.owner_github_id,
        )
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404)
    log_action(db, current_user["github_id"], "delete", "scheduled_scan", schedule_id, program_id)
    db.delete(schedule)
    db.commit()
    return {"message": "Schedule deleted"}
