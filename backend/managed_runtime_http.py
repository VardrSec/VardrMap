"""Unregistered ADR0043 admission and host receipt boundary; no Docker access."""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from sqlalchemy.exc import IntegrityError

from db import get_db
from execution_control import ControlRequest
from managed_http import JOB_PATH, ConsumeInput, _payload
from managed_runtime import BINDING_FIELDS
from managed_wire import WireRefused, canonical
from nm1_authorization import IssuanceRefused

RUNTIME_PATH = "/managed/runtimes/{runtime_id}"
RESPONSE_MAX_BYTES = 16384
Fingerprint = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
Timestamp = Annotated[str, Field(strict=True, min_length=20, max_length=30)]


class IdentityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daemon_id: Identifier
    container_id: Fingerprint
    image_id: Annotated[str, Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")]
    project: Identifier
    started_at: Timestamp
    owner_nonce: Fingerprint


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enrollment_id: Identifier
    runner_id: UUID
    origin: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    identity: IdentityInput
    capability_sha256: Fingerprint
    expires_in_seconds: Annotated[int, Field(strict=True, ge=60, le=604800)]


class RuntimeBindInput(ConsumeInput):
    runtime_id: UUID
    runtime_sha256: Fingerprint


class ExitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_sha256: Fingerprint
    origin: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    job_id: Identifier
    runner_id: UUID
    contract_id: UUID
    attempt_id: UUID
    fence: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
    contract_sha256: Fingerprint
    finished_at: Timestamp
    exit_code: Annotated[int, Field(strict=True, ge=0, le=255)]
    observation_sha256: Fingerprint


class LookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_sha256: Fingerprint


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _operate(service, operation, db, request, runtime_id, body, job_id):
    values = body.model_dump(mode="json")
    if operation == "bind":
        owned_fields = set(ControlRequest.model_fields)
        owned = ControlRequest(**{key: values[key] for key in owned_fields})
        extra = {key: value for key, value in values.items() if key not in owned_fields}
        return service.bind(db, request, job_id=job_id, body=owned, **extra)
    if operation == "observed_exit":
        binding = {key: values.pop(key) for key in BINDING_FIELDS}
        return service.observed_exit(
            db, request, runtime_id=runtime_id, binding=binding, **values
        )
    return getattr(service, operation)(db, request, runtime_id=runtime_id, **values)


def build_runtime_router(service):
    """Explicit Runtimes injection only; registration/activation is separate."""
    router = APIRouter(tags=["managed-runtime-admission-prototype"])

    async def dispatch(request, db, runtime_id, operation, model, job_id=None):
        def refused(status):
            return JSONResponse(
                {"detail": "managed_runtime_refused"},
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )

        try:
            if request.url.scheme != "https":
                return refused(403)
            try:
                body = await _payload(request, model)
            except (WireRefused, ValidationError):
                return refused(422)
            reply = await run_in_threadpool(
                _operate, service, operation, db, request, runtime_id, body, job_id
            )
            if len(canonical(reply)) > RESPONSE_MAX_BYTES:
                return refused(503)
            return JSONResponse(reply, headers={"Cache-Control": "no-store"})
        except HTTPException as error:
            return refused(error.status_code)
        except (WireRefused, IssuanceRefused):
            return refused(409)
        except IntegrityError:
            return refused(409)
        except asyncio.TimeoutError:
            return refused(408)
        except ClientDisconnect:
            return refused(400)
        except Exception:
            return refused(503)

    @router.post(RUNTIME_PATH + "/register")
    async def register(runtime_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, runtime_id, "register", RegisterInput)

    @router.post(RUNTIME_PATH + "/revoke")
    async def revoke(runtime_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, runtime_id, "revoke", RevokeInput)

    @router.post(JOB_PATH + "/runtime-bind")
    async def bind(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, None, "bind", RuntimeBindInput, job_id)

    @router.post(RUNTIME_PATH + "/observed-exit")
    async def observed_exit(runtime_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, runtime_id, "observed_exit", ExitInput)

    @router.post(RUNTIME_PATH + "/receipt")
    async def receipt(runtime_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, runtime_id, "receipt", LookupInput)

    return router
