"""Unregistered human-owner review/receipt boundary; never signs an approval."""

import asyncio
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from db import get_db
from managed_http import JOB_PATH
from managed_wire import WireRefused, canonical, parse
from nm1_authorization import IssuanceRefused

BODY_MAX_BYTES = 1024 * 1024
BODY_TIMEOUT_SECONDS = 3
RESPONSE_MAX_BYTES = 256 * 1024
Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enrollment_id: Identifier
    authorization_id: Identifier
    plan: dict


class ReviewInput(SelectionInput):
    expires_at: Annotated[str, Field(strict=True, min_length=20, max_length=20)]
    max_executions: Annotated[int, Field(strict=True, ge=1)]
    max_duration_seconds: Annotated[int, Field(strict=True, ge=1)]
    max_artifact_bytes: Annotated[int, Field(strict=True, ge=1)]
    credential_grants: list[dict]


class ApprovalEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["vardr.authorization-envelope/1"]
    purpose: Literal["approval"]
    payload: Annotated[str, Field(strict=True, min_length=1, max_length=350000)]
    signature: Annotated[str, Field(strict=True, min_length=1, max_length=128)]


class RegisterInput(SelectionInput):
    approval: ApprovalEnvelope


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
        not length.isascii() or not length.isdecimal() or len(length) > 7
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


def _operate(service, operation, db, request, job_id, body):
    if operation == "review":
        return service.review(db, request, job_id=job_id, **body.model_dump())
    if operation == "register":
        row = service.register(db, request, job_id=job_id, **body.model_dump())
        return {"approval_record_id": row.id}
    service.revoke(db, request, job_id=job_id)
    return {"job_id": job_id, "revoked": True}


def build_approval_router(service):
    """Inject the existing configured Issuer; main never registers this factory.

    Existing owner session/CSRF checks and separately provisioned public operator
    trust authenticate receipts. No private operator key or signer is accepted.
    """
    router = APIRouter(tags=["managed-human-approval-prototype"])

    async def dispatch(request, db, job_id, operation, model):
        def refused(status):
            return JSONResponse(
                {"detail": "managed_approval_refused"},
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )

        try:
            if request.url.scheme != "https":
                return refused(403)
            if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) is None:
                return refused(422)
            try:
                body = await _payload(request, model)
            except (WireRefused, ValidationError):
                return refused(422)
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

    @router.post(JOB_PATH + "/approval/review")
    async def review(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, job_id, "review", ReviewInput)

    @router.post(JOB_PATH + "/approval/register")
    async def register(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, job_id, "register", RegisterInput)

    @router.post(JOB_PATH + "/approval/revoke")
    async def revoke(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, job_id, "revoke", RevokeInput)

    return router
