"""Opt-in Map-owned attempt capacity; never a universal process counter."""

from fastapi import HTTPException
from models import JobExecution, ScanJob


class ConcurrencyBudgetExhausted(HTTPException):
    def __init__(self):
        super().__init__(409, "engagement execution capacity exhausted")


def reserved(db, engagement_id):
    return db.query(JobExecution).join(ScanJob, ScanJob.id == JobExecution.job_id).filter(
        ScanJob.program_id == engagement_id, JobExecution.capacity_reserved.is_(True)
    ).count()


def require_idle(db, engagement_id):
    if reserved(db, engagement_id) or db.query(ScanJob).filter_by(
        program_id=engagement_id, status="running"
    ).first():
        raise HTTPException(409, "running or unresolved work prevents policy change or deletion")


def before_claim(db, engagement, body):
    opted_in = body is not None and body.concurrency_budget
    if engagement.concurrency_limit is None:
        if opted_in:
            raise HTTPException(409, "explicit engagement concurrency policy required")
        return
    if not opted_in:
        raise HTTPException(409, "engagement requires budgeted owned execution")
    if reserved(db, engagement.id) >= engagement.concurrency_limit:
        raise ConcurrencyBudgetExhausted()
