"""Opt-in bounded execution control. This is not execution authorization or a worker."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from models import Engagement, JobExecution, ScanJob
from deps import accessible_engagement_ids


def lock_job(db: Session, job_id: str, user: dict):
    """One lock order for claim/stop/control/finish: engagement, job, execution.

    The parent lookup acquires no lock; the engagement FK cannot change through
    a job update. Authorization still runs in the caller before any mutation.
    """
    parent = (
        db.query(ScanJob.program_id)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(user["github_id"], db)),
        )
        .scalar()
    )
    if parent is None:
        raise HTTPException(404)
    db.query(Engagement).filter_by(
        id=parent
    ).with_for_update().populate_existing().one()
    return (
        db.query(ScanJob)
        .filter_by(id=job_id)
        .with_for_update()
        .populate_existing()
        .one()
    )


LEASE_SECONDS = 10


def no_store(response: Response | None):
    if response is not None:
        response.headers["Cache-Control"] = "no-store"


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TargetBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["gate-fixed-http/1"]
    case_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    origins: list[str] = Field(min_length=1, max_length=100)


class ClaimControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runner_id: UUID
    origin: str = Field(max_length=500)
    concurrency_budget: bool = Field(default=False, strict=True)
    target_binding: TargetBinding | None = None

    @field_validator("origin")
    @classmethod
    def origin_valid(cls, value):
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or value.endswith("/")
            or (
                parts.scheme == "http"
                and parts.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ValueError("explicit HTTPS Map origin required (HTTP loopback only)")
        return value


class ControlRequest(ClaimControl):
    token: str = Field(min_length=32, max_length=100)


class FinishControl(ControlRequest):
    outcome: Literal["completed", "failed", "cancelled", "uncertain"]


def principal(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer vmap_"):
        raise HTTPException(403, "controlled execution requires an API key")
    return hashlib.sha256(authorization.encode()).hexdigest()


def issue(db: Session, job_id: str, user: dict, request: Request, body: ClaimControl, target_receipt=None):
    token = secrets.token_urlsafe(32)
    row = JobExecution(
        job_id=job_id,
        runner_id=str(body.runner_id),
        origin=body.origin,
        owner=user["github_id"],
        principal_hash=principal(request),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=now() + timedelta(seconds=LEASE_SECONDS),
        state="active",
        capacity_reserved=body.concurrency_budget,
        target_charge=target_receipt["charged"] if target_receipt else 0,
        target_binding=target_receipt["binding"] if target_receipt else None,
    )
    db.add(row)
    return {**binding(row), "token": token, "lease_seconds": LEASE_SECONDS,
            **({"capacity_reserved": True} if body.concurrency_budget else {}),
            **({"target_budget": target_receipt} if target_receipt else {})}


def binding(row):
    return {"job_id": row.job_id, "runner_id": row.runner_id, "origin": row.origin}


def owned(db: Session, job_id: str, user: dict, request: Request, body: ControlRequest):
    lock_job(db, job_id, user)
    row = db.query(JobExecution).filter_by(job_id=job_id).with_for_update().first()
    if (
        not row
        or row.owner != user["github_id"]
        or row.runner_id != str(body.runner_id)
        or row.origin != body.origin
        or row.principal_hash != principal(request)
        or not hmac.compare_digest(
            row.token_hash, hashlib.sha256(body.token.encode()).hexdigest()
        )
    ):
        raise HTTPException(404)
    return row
