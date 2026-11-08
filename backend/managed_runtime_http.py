"""Unregistered ADR0043 admission and host receipt boundary; no Docker access."""

import asyncio
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from sqlalchemy.exc import IntegrityError

from db import get_db
from execution_control import ControlRequest
from managed_http import JOB_PATH, ConsumeInput, _payload
from managed_runtime import BINDING_FIELDS
from managed_persistent_http import Attempt, Last, LimitsInput, ReportingInput, paired_admission
from managed_persistent_wire import sequence
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
    expires_in_seconds: Annotated[int, Field(strict=True, ge=60, le=604800)] | None = None
    max_attempts: Annotated[int, Field(strict=True, ge=1, le=32)] | None = None
    mode: Literal["persistent"] | None = None
    limits: LimitsInput | None = None
    reporting_authority: ReportingInput | None = None

    @model_validator(mode="after")
    def explicit_bound(self):
        if self.mode == "persistent":
            if (self.limits is None or self.reporting_authority is None
                    or self.model_fields_set & {"expires_in_seconds", "max_attempts"}):
                raise ValueError("persistent_admission_policy_required")
            return self
        if (self.expires_in_seconds is None
                or self.model_fields_set & {"mode", "limits", "reporting_authority"}):
            raise ValueError("finite_admission_policy_required")
        if "max_attempts" in self.model_fields_set and self.max_attempts is None:
            raise ValueError("explicit_attempt_bound_required")
        return self


class RuntimeBindInput(ConsumeInput):
    runtime_id: UUID
    runtime_sha256: Fingerprint
    runtime_sequence: Attempt | None = None
    admission_sha256: Fingerprint | None = None

    @model_validator(mode="after")
    def explicit_sequence(self):
        if "runtime_sequence" in self.model_fields_set and self.runtime_sequence is None:
            raise ValueError("explicit_sequence_required")
        return paired_admission(self)


class ReleaseInput(RuntimeBindInput):
    runtime_sequence: Attempt
    terminal_receipt_sha256: Fingerprint
    native_done_sha256: Fingerprint


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
    runtime_sequence: Attempt | None = None
    admission_sha256: Fingerprint | None = None

    @model_validator(mode="after")
    def explicit_sequence(self):
        if "runtime_sequence" in self.model_fields_set and self.runtime_sequence is None:
            raise ValueError("explicit_sequence_required")
        return paired_admission(self)


class LookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_sha256: Fingerprint
    admission_sha256: Fingerprint | None = None

    @model_validator(mode="after")
    def explicit_admission(self):
        if "admission_sha256" in self.model_fields_set and self.admission_sha256 is None:
            raise ValueError("persistent_admission_required")
        return self


class DisableInput(LookupInput):
    admission_sha256: Fingerprint


class UnboundExitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_sha256: Fingerprint
    finished_at: Timestamp
    exit_code: Annotated[int, Field(strict=True, ge=0, le=255)]
    observation_sha256: Fingerprint
    last_sequence: Last | None = None
    admission_sha256: Fingerprint | None = None

    @model_validator(mode="after")
    def explicit_sequence(self):
        if "last_sequence" in self.model_fields_set and self.last_sequence is None:
            raise ValueError("explicit_sequence_required")
        return paired_admission(self, last=True)


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _operate(service, operation, db, request, runtime_id, body, job_id, runtime_sequence=None):
    values = body.model_dump(mode="json")
    if operation == "history":
        return service.history(db, request, runtime_id=runtime_id,
                               runtime_sequence=runtime_sequence, **values)
    if operation in {"bind", "release"}:
        owned_fields = set(ControlRequest.model_fields)
        owned = ControlRequest(**{key: values[key] for key in owned_fields})
        extra = {key: value for key, value in values.items() if key not in owned_fields}
        return getattr(service, operation)(db, request, job_id=job_id, body=owned, **extra)
    if operation == "observed_exit":
        binding = {key: values.pop(key) for key in BINDING_FIELDS}
        return service.observed_exit(
            db, request, runtime_id=runtime_id, binding=binding, **values
        )
    return getattr(service, operation)(db, request, runtime_id=runtime_id, **values)


def build_runtime_router(service):
    """Explicit Runtimes injection only; registration/activation is separate."""
    router = APIRouter(tags=["managed-runtime-admission-prototype"])

    async def dispatch(request, db, runtime_id, operation, model, job_id=None, runtime_sequence=None):
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
                if runtime_sequence is not None:
                    if body.admission_sha256 is not None:
                        sequence(runtime_sequence, 1)
                    else:
                        runtime_sequence = int(runtime_sequence)
                        if not 1 <= runtime_sequence <= 32:
                            return refused(422)
            except (WireRefused, ValidationError, ValueError):
                return refused(422)
            reply = await run_in_threadpool(
                _operate, service, operation, db, request, runtime_id, body, job_id, runtime_sequence
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

    @router.post(RUNTIME_PATH + "/disable")
    async def disable(runtime_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, runtime_id, "disable", DisableInput)

    @router.post(JOB_PATH + "/runtime-bind")
    async def bind(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, None, "bind", RuntimeBindInput, job_id)

    @router.post(JOB_PATH + "/runtime-idle-release")
    async def release(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, None, "release", ReleaseInput, job_id)

    @router.post(RUNTIME_PATH + "/observed-exit")
    async def observed_exit(runtime_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, runtime_id, "observed_exit", ExitInput)

    @router.post(RUNTIME_PATH + "/receipt")
    async def receipt(runtime_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, runtime_id, "receipt", LookupInput)

    @router.post(RUNTIME_PATH + "/attempts/{runtime_sequence}/receipt")
    async def history(runtime_id: str, runtime_sequence: str, request: Request, db=Depends(get_db)):
        return await dispatch(request, db, runtime_id, "history", LookupInput,
                              runtime_sequence=runtime_sequence)

    @router.post(RUNTIME_PATH + "/observed-unbound-exit")
    async def observed_unbound_exit(
        runtime_id: str, request: Request, db=Depends(get_db)
    ):
        return await dispatch(
            request, db, runtime_id, "observed_unbound_exit", UnboundExitInput
        )

    return router
