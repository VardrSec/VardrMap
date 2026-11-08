"""Strict additive v3 field types shared by existing managed HTTP boundaries."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from managed_persistent_wire import sequence
from managed_wire import WireRefused


def _counter(value):
    try:
        sequence(value)
    except WireRefused:
        raise ValueError("invalid_runtime_sequence") from None
    return value


def _positive(value):
    if value == "0":
        raise ValueError("invalid_runtime_sequence")
    return value


Counter = Annotated[str, Field(strict=True), AfterValidator(_counter)]
Sequence = Annotated[Counter, AfterValidator(_positive)]
Attempt = Annotated[int, Field(strict=True, ge=1, le=32)] | Sequence
Last = Annotated[int, Field(strict=True, ge=0, le=32)] | Counter
Fingerprint = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


class LimitsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: Sequence | None
    idle_timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)] | None


class ReportingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["worker-stop-only"]
    expires_at: None


class CursorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    last_sequence: Counter
    phase: Literal["active", "idle"]


def paired_admission(body, *, last=False):
    supplied = "admission_sha256" in body.model_fields_set
    value = body.last_sequence if last else body.runtime_sequence
    if supplied:
        if body.admission_sha256 is None or type(value) is not str:
            raise ValueError("persistent_sequence_required")
    elif type(value) is str:
        raise ValueError("persistent_admission_required")
    return body
