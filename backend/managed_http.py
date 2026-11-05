"""Unregistered managed discovery/claim/control boundary; no bootstrap or worker."""

import asyncio
import hashlib
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

import execution_control as control
from db import get_db
from deps import accessible_engagement_ids, get_current_user
from managed_wire import WireRefused, canonical, parse, require
from models import AuthorizationTestCase, ManagedApproval, ManagedEnrollment, ScanJob
from nm1_authorization import IssuanceRefused

PENDING_PATH = "/jobs/managed/pending"
JOB_PATH = "/jobs/{job_id}/managed"
BODY_MAX_BYTES = 8192
BODY_TIMEOUT_SECONDS = 3
RESPONSE_MAX_BYTES = 256 * 1024
Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class PendingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    runner_id: UUID
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 20
    after: Identifier | None = None


class ManagedControlInput(control.ControlRequest):
    contract_id: UUID
    attempt_id: UUID
    fence: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]


class ConsumeInput(ManagedControlInput):
    contract_sha256: Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


async def _payload(request, model):
    if (
        request.headers.get("content-type", "").split(";")[0].lower()
        != "application/json"
    ):
        raise HTTPException(415)
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415)
    length = request.headers.get("content-length")
    if length is not None and (
        not length.isascii() or not length.isdecimal() or len(length) > 6
    ):
        raise HTTPException(422)
    if length is not None and int(length) > BODY_MAX_BYTES:
        raise HTTPException(413)

    async def read():
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > BODY_MAX_BYTES:
                raise HTTPException(413)
            data.extend(chunk)
        return bytes(data)

    raw = await asyncio.wait_for(read(), timeout=BODY_TIMEOUT_SECONDS)
    return model.model_validate(parse(raw, BODY_MAX_BYTES))


def _pending(service, db, request, body):
    """Bounded discovery only: listing neither reserves nor grants execution."""
    with service.operation(db) as now:
        user = get_current_user(
            request, authorization=request.headers.get("authorization"), db=db
        )
        principal = control.principal(request)  # Sessions/UUIDs cannot replace the key.
        require(body.origin == service.origin, "configured_origin_required")
        enrollment = (
            db.query(ManagedEnrollment)
            .filter_by(
                owner=user["github_id"],
                principal_hash=principal,
                runner_id=str(body.runner_id),
                origin=service.origin,
            )
            .one_or_none()
        )
        if enrollment is None:
            raise HTTPException(404)
        enrollment, key = service._enrollment(db, enrollment.id, user["github_id"])
        header = request.headers["authorization"]
        require(
            hashlib.sha256(header.removeprefix("Bearer ").encode()).hexdigest()
            == key.key_hash,
            "enrollment_key_unavailable",
        )
        query = (
            db.query(ScanJob, ManagedApproval)
            .join(
                ManagedApproval,
                ScanJob.managed_approval_id == ManagedApproval.id,
            )
            .filter(
                ScanJob.status == "pending",
                ScanJob.authorization_contract_required.is_(True),
                ScanJob.program_id.in_(
                    accessible_engagement_ids(user["github_id"], db)
                ),
                ScanJob.tool_type == "vardrgate_api_test",
                ManagedApproval.job_id == ScanJob.id,
                ManagedApproval.engagement_id == ScanJob.program_id,
                ManagedApproval.owner == user["github_id"],
                ManagedApproval.enrollment_id == enrollment.id,
                ManagedApproval.revoked.is_(False),
            )
        )
        if body.after is not None:
            query = query.filter(ScanJob.id > body.after)
        rows = query.order_by(ScanJob.id).limit(body.limit + 1).all()
        jobs = []
        for job, approval in rows[: body.limit]:
            # Verify the stored human signature/window, not current authority or
            # capacity. Claim reprojects authority and atomically charges budgets.
            try:
                service.wire.approval(
                    approval.envelope, approval.context, approval.owner, now()
                )
            except WireRefused:
                continue
            case = db.get(AuthorizationTestCase, (job.config or {}).get("test_case_id"))
            if case is None or case.program_id != job.program_id:
                continue
            jobs.append(
                {
                    "id": job.id,
                    "program_id": job.program_id,
                    "tool_type": job.tool_type,
                    "authorization_contract_required": True,
                    "config": {"test_case": case.spec},
                    "plan": approval.plan,
                }
            )
        reply = {
            "jobs": jobs,
            "next_after": rows[body.limit - 1][0].id
            if len(rows) > body.limit
            else None,
        }
        db.rollback()  # No lease, claim, counter, reservation or approval mutation.
        return reply


def _operate(service, operation, db, request, job_id, body):
    if operation == "claim":
        reply = service.claim(db, request, job_id=job_id, body=body)
        # This is the retained claim snapshot, never the polled or later live case.
        snapshot = db.get(ScanJob, job_id).case_snapshot
        require(type(snapshot) is dict, "frozen_case_required")
        return {**reply, "config": {"test_case": snapshot}}
    args = {
        name: getattr(body, name) for name in ("contract_id", "attempt_id", "fence")
    }
    args.update(
        contract_id=str(args["contract_id"]), attempt_id=str(args["attempt_id"])
    )
    if operation == "consume":
        args["contract_sha256"] = body.contract_sha256
    owned = control.ControlRequest(**body.model_dump(exclude=set(args)))
    return getattr(service, operation)(db, request, job_id=job_id, body=owned, **args)


def build_managed_router(service):
    """Explicitly injected Issuer only; main never constructs or registers it.

    No keys, environment settings or enrollment state are created/read implicitly.
    Approval, finalization, recovery and worker activation remain separate gates.
    """
    router = APIRouter(tags=["managed-runtime-prototype"])

    async def dispatch(request, db, operation, model, job_id=None):
        def refused(status):
            return JSONResponse(
                {"detail": "managed_request_refused"},
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )

        try:
            if request.url.scheme != "https":
                return refused(403)
            if (
                job_id is not None
                and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) is None
            ):
                return refused(422)
            try:
                body = await _payload(request, model)
            except (WireRefused, ValidationError):
                return refused(422)
            if operation == "pending":
                reply = await run_in_threadpool(_pending, service, db, request, body)
            else:
                reply = await run_in_threadpool(
                    _operate, service, operation, db, request, job_id, body
                )
            if len(canonical(reply)) > RESPONSE_MAX_BYTES:
                return refused(503)
            return JSONResponse(reply, headers={"Cache-Control": "no-store"})
        except HTTPException as error:
            return refused(error.status_code)
        except (WireRefused, IssuanceRefused):
            return refused(409)
        except asyncio.TimeoutError:
            return refused(408)
        except ClientDisconnect:
            return refused(400)
        except Exception:
            return refused(503)

    @router.post(PENDING_PATH)
    async def pending(request: Request, db=Depends(get_db)):
        return await dispatch(request, db, "pending", PendingInput)

    @router.post(JOB_PATH + "/claim")
    async def claim(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, "claim", control.ClaimControl, job_id)

    @router.post(JOB_PATH + "/current")
    async def current(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, "current", ManagedControlInput, job_id)

    @router.post(JOB_PATH + "/refresh")
    async def refresh(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, "refresh", ManagedControlInput, job_id)

    @router.post(JOB_PATH + "/consume")
    async def consume(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, "consume", ConsumeInput, job_id)

    return router
