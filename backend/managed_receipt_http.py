"""Unregistered owned result/stop receipts; no execution, renewal or bootstrap."""

import asyncio
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from db import get_db
from execution_control import ControlRequest
from managed_http import JOB_PATH, ConsumeInput
from managed_stops import Stops
from managed_wire import WireRefused, canonical, parse
from nm1_authorization import IssuanceRefused

RESULT_BODY_MAX_BYTES = 1024 * 1024
CONTROL_BODY_MAX_BYTES = 8192
BODY_TIMEOUT_SECONDS = 3
RESPONSE_MAX_BYTES = 16384
Fingerprint = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


class ResultInput(ConsumeInput):
    artifact: Annotated[str, Field(strict=True, min_length=1, max_length=512000)]
    artifact_sha256: Fingerprint


class CompletionInput(ConsumeInput):
    outcome: Literal["completed", "failed", "cancelled"]
    termination_confirmed: Annotated[bool, Field(strict=True)]


class FinishInput(CompletionInput):
    receipt_sha256: Fingerprint


class StopInput(CompletionInput):
    cause: Annotated[str, Field(strict=True, min_length=1, max_length=64)]


async def _payload(request, model, maximum):
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
    if length is not None and int(length) > maximum:
        raise HTTPException(413)

    async def read():
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > maximum:
                raise HTTPException(413)
            data.extend(chunk)
        return bytes(data)

    raw = await asyncio.wait_for(read(), timeout=BODY_TIMEOUT_SECONDS)
    return model.model_validate(parse(raw, maximum))


def _operate(service, operation, db, request, job_id, body):
    owned_fields = set(ControlRequest.model_fields)
    owned = ControlRequest(**body.model_dump(include=owned_fields))
    args = body.model_dump(exclude=owned_fields)
    for name in ("contract_id", "attempt_id"):
        args[name] = str(args[name])
    return getattr(service, operation)(db, request, job_id=job_id, body=owned, **args)


def build_receipt_router(results):
    """Explicit existing Results injection; main never calls this factory.

    Stops shares that same issuer/ownership protocol. These adapters neither
    infer process termination nor restore permission from a retained receipt.
    """
    stops = Stops(results)
    router = APIRouter(tags=["managed-receipt-prototype"])

    async def dispatch(request, db, job_id, service, operation, model, maximum):
        def refused(status):
            return JSONResponse(
                {"detail": "managed_receipt_refused"},
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )

        try:
            if request.url.scheme != "https":
                return refused(403)
            if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) is None:
                return refused(422)
            try:
                body = await _payload(request, model, maximum)
            except (WireRefused, ValidationError):
                return refused(422)
            reply = await run_in_threadpool(
                _operate,
                service,
                operation,
                db,
                request,
                job_id,
                body,
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

    @router.post(JOB_PATH + "/result")
    async def submit(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(
            request,
            db,
            job_id,
            results,
            "submit",
            ResultInput,
            RESULT_BODY_MAX_BYTES,
        )

    @router.post(JOB_PATH + "/finish")
    async def finish(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(
            request,
            db,
            job_id,
            results,
            "finish",
            FinishInput,
            CONTROL_BODY_MAX_BYTES,
        )

    @router.post(JOB_PATH + "/stopped")
    async def stopped(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(
            request,
            db,
            job_id,
            stops,
            "report",
            StopInput,
            CONTROL_BODY_MAX_BYTES,
        )

    @router.post(JOB_PATH + "/stop-status")
    async def inspect(job_id: str, request: Request, db=Depends(get_db)):
        return await dispatch(
            request,
            db,
            job_id,
            stops,
            "inspect",
            ConsumeInput,
            CONTROL_BODY_MAX_BYTES,
        )

    return router
