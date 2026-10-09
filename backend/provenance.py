"""Validate engagement ownership and link each execution to its observed inventory."""
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from models import JobResultLink, ScanJob


def require_job(db, program_id: str, job_id: str | None):
    if not job_id:
        return None
    job = db.query(ScanJob).filter(ScanJob.id == job_id, ScanJob.program_id == program_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def link_result(db, job_id: str | None, kind: str, item_id: str):
    if not job_id:
        return
    column = getattr(JobResultLink, kind + "_id")
    if db.query(JobResultLink.id).filter(JobResultLink.job_id == job_id, column == item_id).first():
        return
    # A repeated chunk or simultaneous observation must not abort the import.
    try:
        with db.begin_nested():
            db.add(JobResultLink(job_id=job_id, **{kind + "_id": item_id}))
            db.flush()
    except IntegrityError:
        if not db.query(JobResultLink.id).filter(JobResultLink.job_id == job_id, column == item_id).first():
            raise
