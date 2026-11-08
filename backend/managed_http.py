"""Unregistered managed discovery/claim/control boundary; no bootstrap or worker."""

import asyncio
import hashlib
import logging
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

import execution_control as control
from concurrency_budget import ConcurrencyBudgetExhausted
from db import get_db
from deps import accessible_engagement_ids, get_current_user
from duration_budget import DurationBudgetExhausted
from managed_wire import WireRefused, canonical, parse, require
from managed_persistent_http import Attempt, CursorInput, Fingerprint, paired_admission
from models import AuthorizationTestCase, Engagement, ManagedApproval, ManagedEnrollment, ScanJob
from nm1_authorization import IssuanceRefused
from target_budget import TargetBudgetExhausted

logger = logging.getLogger(__name__)

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
    runtime_id: UUID | None = None
    runtime_sha256: Fingerprint | None = None
    admission_sha256: Fingerprint | None = None
    cursor: CursorInput | None = None

    @model_validator(mode="after")
    def persistent_presence(self):
        supplied = self.model_fields_set & {"runtime_id", "runtime_sha256", "admission_sha256", "cursor"}
        if supplied and (len(supplied) != 4 or any(getattr(self, name) is None for name in supplied)):
            raise ValueError("persistent_presence_required")
        return self


class ManagedControlInput(control.ControlRequest):
    contract_id: UUID
    attempt_id: UUID
    fence: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]


class ConsumeInput(ManagedControlInput):
    contract_sha256: Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


class ClaimInput(control.ClaimControl):
    runtime_id: UUID | None = None
    runtime_sha256: (
        Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")] | None
    ) = None
    runtime_sequence: Attempt | None = None
    admission_sha256: Fingerprint | None = None

    @model_validator(mode="after")
    def paired_runtime(self):
        if (self.runtime_id is None) != (self.runtime_sha256 is None):
            raise ValueError("paired_runtime_required")
        if "runtime_sequence" in self.model_fields_set and (
            self.runtime_sequence is None or self.runtime_id is None or self.runtime_sha256 is None
        ):
            raise ValueError("sequence_runtime_required")
        return paired_admission(self)


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


def _pending(service, db, request, body, runtimes=None):
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
        presence = None
        if body.admission_sha256 is not None:
            require(runtimes is not None, "runtime_admission_unavailable")
            presence = runtimes.persistent.pending(db, enrollment, body, now)
        query = (
            db.query(ScanJob, ManagedApproval)
            .join(
                ManagedApproval,
                ScanJob.managed_approval_id == ManagedApproval.id,
            )
            .join(Engagement, ScanJob.program_id == Engagement.id)
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
                Engagement.stop_work_at.is_(None),
                ManagedApproval.revision == Engagement.managed_authority_revision,
            )
        )
        if body.after is not None:
            query = query.filter(ScanJob.id > body.after)
        rows = query.order_by(ScanJob.id).limit(body.limit + 1).all()
        jobs = []
        for job, approval in rows[: body.limit]:
            # Verify the stored human signature/window. Claim still reprojects
            # all current authority and atomically charges budgets.
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
        if presence is not None:
            service._locked_time(db, now)  # Runtime is already locked; no permission renewal.
            reply["availability"] = runtimes.persistent.availability(presence, now().replace(tzinfo=None))
            db.commit()
        else:
            db.rollback()  # Legacy listing has no presence/lease/accounting mutation.
        return reply


def _operate(service, operation, db, request, job_id, body, runtimes=None):
    if operation == "claim":
        claim = control.ClaimControl(
            **body.model_dump(exclude={"runtime_id", "runtime_sha256", "runtime_sequence", "admission_sha256"})
        )
        if body.runtime_id is not None:
            require(runtimes is not None, "runtime_admission_unavailable")
            reply = runtimes.claim(
                db,
                request,
                job_id=job_id,
                body=claim,
                runtime_id=str(body.runtime_id),
                runtime_sha256=body.runtime_sha256,
                runtime_sequence=body.runtime_sequence,
                admission_sha256=body.admission_sha256,
            )
        else:
            reply = service.claim(db, request, job_id=job_id, body=claim)
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
    hooks = ({"on_control": runtimes.persistent.control_guard}
             if runtimes is not None else {})
    return getattr(service, operation)(db, request, job_id=job_id, body=owned, **args, **hooks)


def build_managed_router(service, runtimes=None):
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
                reply = await run_in_threadpool(_pending, service, db, request, body, runtimes)
            else:
                reply = await run_in_threadpool(
                    _operate, service, operation, db, request, job_id, body, runtimes
                )
            if len(canonical(reply)) > RESPONSE_MAX_BYTES:
                return refused(503)
            return JSONResponse(reply, headers={"Cache-Control": "no-store"})
        except DurationBudgetExhausted as error:
            # Issuer.operation has rolled back before the refusal reaches HTTP.
            if operation == "claim":
                logger.warning("managed_claim_duration_exhausted")
            return refused(error.status_code)
        except TargetBudgetExhausted as error:
            # The issuer has rolled back the claim before reporting refusal.
            if operation == "claim":
                logger.warning("managed_claim_target_exhausted")
            return refused(error.status_code)
        except ConcurrencyBudgetExhausted as error:
            # The issuer has rolled back the claim before reporting refusal.
            if operation == "claim":
                logger.warning("managed_claim_concurrency_exhausted")
            return refused(error.status_code)
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
        return await dispatch(request, db, "claim", ClaimInput, job_id)

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
