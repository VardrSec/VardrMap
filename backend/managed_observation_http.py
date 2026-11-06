"""Unregistered read-only managed observation router; no issuer/bootstrap activation."""

import asyncio
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from db import get_db
from execution_control import ClaimControl
from managed_wire import WireRefused, canonical, parse
from nm1_authorization import IssuanceRefused

OBSERVATION_PATH = "/jobs/{job_id}/managed/observation"
BODY_MAX_BYTES = 8192
BODY_TIMEOUT_SECONDS = 3
Fingerprint = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    runner_id: UUID
    plan_sha256: Fingerprint
    case_sha256: Fingerprint
    association_sha256: Fingerprint
    runtime_id: UUID | None = None
    runtime_sha256: Fingerprint | None = None

    @model_validator(mode="after")
    def paired_runtime(self):
        supplied = self.model_fields_set & {"runtime_id", "runtime_sha256"}
        if supplied and (len(supplied) != 2 or self.runtime_id is None or self.runtime_sha256 is None):
            raise ValueError("paired_runtime_observation_required")
        return self


async def _payload(request):
    """Bound bytes and total body-read wait before strict JSON/model decoding."""
    if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
        raise HTTPException(415)
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415)
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdecimal():
            raise HTTPException(422)
        if len(length) > 6 or int(length) > BODY_MAX_BYTES:
            raise HTTPException(413)

    async def read():
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > BODY_MAX_BYTES:
                raise HTTPException(413)
            data.extend(chunk)
        return bytes(data)

    raw = await asyncio.wait_for(read(), timeout=BODY_TIMEOUT_SECONDS)
    return ObservationInput.model_validate(parse(raw, BODY_MAX_BYTES))


def _refused(status):
    return JSONResponse(
        {"detail": "managed_observation_refused"},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def build_observation_router(service):
    """Inject the existing Observations service explicitly; main never calls this.

    No keys/configuration are read and no service is constructed or registered
    implicitly. This factory exposes observation only, never permission mutation.
    """
    router = APIRouter(tags=["managed-observation-prototype"])

    @router.post(
        OBSERVATION_PATH,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": ObservationInput.model_json_schema()}},
            }
        },
    )
    async def observe(job_id: str, request: Request, db=Depends(get_db)):
        try:
            if request.url.scheme != "https":
                return _refused(403)
            if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) is None:
                return _refused(422)
            try:
                body = await _payload(request)
            except (WireRefused, ValidationError):
                return _refused(422)
            reply = await run_in_threadpool(
                service.inspect,
                db,
                request,
                job_id=job_id,
                body=ClaimControl(origin=body.origin, runner_id=body.runner_id),
                plan_sha256=body.plan_sha256,
                case_sha256=body.case_sha256,
                association_sha256=body.association_sha256,
                **(
                    {"runtime_id": str(body.runtime_id), "runtime_sha256": body.runtime_sha256}
                    if body.runtime_id is not None else {}
                ),
            )
            if len(canonical(reply)) > 16384:
                return _refused(503)
            return JSONResponse(reply, headers={"Cache-Control": "no-store"})
        except HTTPException as error:
            return _refused(error.status_code)
        except (WireRefused, IssuanceRefused):
            return _refused(409)
        except asyncio.TimeoutError:
            return _refused(408)
        except ClientDisconnect:
            return _refused(400)
        except Exception:
            # Never expose an authenticated header, request body or DB failure.
            return _refused(503)

    return router
