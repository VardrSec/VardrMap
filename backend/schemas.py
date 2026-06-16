from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from security import sanitize_identifier, strip_html, validate_safe_url

Severity = Literal["info", "low", "medium", "high", "critical"]
FindingStatus = Literal["new", "candidate", "triaged", "in_progress", "closed"]
ManualStatus = Literal["new", "in_progress", "validated", "closed"]
ScanStatus = Literal["new", "reviewed", "false_positive", "promoted"]
ScopeKind = Literal["domain", "subdomain", "url", "cidr", "api", "mobile"]
ReportStatus = Literal["draft", "submitted", "accepted", "duplicate", "informative", "resolved"]
ToolType = Literal["ffuf", "httpx", "nuclei"]


class ProgramCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    platform: Optional[str] = Field(default="", max_length=80)
    program_url: Optional[str] = Field(default="", max_length=500)
    scope_summary: Optional[str] = Field(default="", max_length=5000)
    severity_guidance: Optional[str] = Field(default="", max_length=5000)
    safe_harbor_notes: Optional[str] = Field(default="", max_length=5000)

    @field_validator("name", "platform", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v)

    @field_validator("scope_summary", "severity_guidance", "safe_harbor_notes", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v)

    @field_validator("program_url", mode="before")
    @classmethod
    def sanitize_url(cls, v): return validate_safe_url(v)


class ProgramUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    platform: Optional[str] = Field(default=None, max_length=80)
    program_url: Optional[str] = Field(default=None, max_length=500)
    scope_summary: Optional[str] = Field(default=None, max_length=5000)
    severity_guidance: Optional[str] = Field(default=None, max_length=5000)
    safe_harbor_notes: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("name", "platform", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v) if v is not None else v

    @field_validator("scope_summary", "severity_guidance", "safe_harbor_notes", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v) if v is not None else v

    @field_validator("program_url", mode="before")
    @classmethod
    def sanitize_url(cls, v): return validate_safe_url(v) if v is not None else v


class ScopeItemCreate(BaseModel):
    value: str = Field(min_length=1, max_length=500)
    kind: ScopeKind = "domain"
    notes: Optional[str] = Field(default="", max_length=2000)

    @field_validator("value", mode="before")
    @classmethod
    def sanitize_value(cls, v): return sanitize_identifier(v)

    @field_validator("notes", mode="before")
    @classmethod
    def sanitize_notes(cls, v): return strip_html(v)


class ManualTestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    hypothesis: Optional[str] = Field(default="", max_length=5000)
    payload: Optional[str] = Field(default="", max_length=10000)
    evidence: Optional[str] = Field(default="", max_length=10000)
    status: ManualStatus = "new"

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v): return sanitize_identifier(v)

    @field_validator("hypothesis", "evidence", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v)
    # payload intentionally not stripped — users paste raw HTTP/code here


class ManualTestUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    hypothesis: Optional[str] = Field(default=None, max_length=5000)
    payload: Optional[str] = Field(default=None, max_length=10000)
    evidence: Optional[str] = Field(default=None, max_length=10000)
    status: Optional[ManualStatus] = None

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v): return sanitize_identifier(v) if v is not None else v

    @field_validator("hypothesis", "evidence", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v) if v is not None else v
    # payload intentionally not stripped


class FindingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    severity: Severity = "info"
    asset: Optional[str] = Field(default="", max_length=500)
    status: FindingStatus = "new"
    summary: Optional[str] = Field(default="", max_length=5000)
    steps: Optional[str] = Field(default="", max_length=10000)
    impact: Optional[str] = Field(default="", max_length=5000)
    remediation: Optional[str] = Field(default="", max_length=5000)

    @field_validator("title", "asset", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v) if v is not None else v

    @field_validator("summary", "steps", "impact", "remediation", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v)


class FindingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    severity: Optional[Severity] = None
    asset: Optional[str] = Field(default=None, max_length=500)
    status: Optional[FindingStatus] = None
    summary: Optional[str] = Field(default=None, max_length=5000)
    steps: Optional[str] = Field(default=None, max_length=10000)
    impact: Optional[str] = Field(default=None, max_length=5000)
    remediation: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("title", "asset", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v) if v is not None else v

    @field_validator("summary", "steps", "impact", "remediation", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v) if v is not None else v


class ReportCreate(BaseModel):
    finding_id: Optional[str] = Field(default="", max_length=100)
    title: str = Field(min_length=1, max_length=200)
    summary: Optional[str] = Field(default="", max_length=5000)
    steps: Optional[str] = Field(default="", max_length=10000)
    impact: Optional[str] = Field(default="", max_length=5000)
    remediation: Optional[str] = Field(default="", max_length=5000)
    cwe: Optional[str] = Field(default="", max_length=50)
    cvss: Optional[str] = Field(default="", max_length=50)
    status: ReportStatus = "draft"

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v): return sanitize_identifier(v)

    @field_validator("summary", "steps", "impact", "remediation", "cwe", "cvss", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v)


class ReportUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=5000)
    steps: Optional[str] = Field(default=None, max_length=10000)
    impact: Optional[str] = Field(default=None, max_length=5000)
    remediation: Optional[str] = Field(default=None, max_length=5000)
    cwe: Optional[str] = Field(default=None, max_length=50)
    cvss: Optional[str] = Field(default=None, max_length=50)
    status: Optional[ReportStatus] = None

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v): return sanitize_identifier(v) if v is not None else v

    @field_validator("summary", "steps", "impact", "remediation", "cwe", "cvss", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v) if v is not None else v


class ScanStatusUpdate(BaseModel):
    status: ScanStatus


class BulkScanStatusUpdate(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    status: ScanStatus


SubmissionStatus = Literal["submitted", "triaged", "accepted", "duplicate", "na", "paid", "rejected"]


class SubmissionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    platform: Optional[str] = Field(default="", max_length=50)
    platform_reference: Optional[str] = Field(default="", max_length=200)
    finding_id: Optional[str] = Field(default="", max_length=100)
    report_id: Optional[str] = Field(default="", max_length=100)
    severity: Optional[str] = Field(default="", max_length=20)
    status: SubmissionStatus = "submitted"
    payout_usd: Optional[float] = None
    notes: Optional[str] = Field(default="", max_length=5000)

    @field_validator("title", "platform", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v) if v else ""

    @field_validator("notes", mode="before")
    @classmethod
    def sanitize_notes(cls, v): return strip_html(v) if v else ""


class SubmissionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    platform: Optional[str] = Field(default=None, max_length=50)
    platform_reference: Optional[str] = Field(default=None, max_length=200)
    finding_id: Optional[str] = Field(default=None, max_length=100)
    report_id: Optional[str] = Field(default=None, max_length=100)
    severity: Optional[str] = Field(default=None, max_length=20)
    status: Optional[SubmissionStatus] = None
    payout_usd: Optional[float] = None
    resolved_at: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("title", "platform", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v) if v is not None else v

    @field_validator("notes", mode="before")
    @classmethod
    def sanitize_notes(cls, v): return strip_html(v) if v is not None else v


class ApiKeyCreate(BaseModel):
    label: Optional[str] = Field(default="", max_length=100)
    scope: Optional[Literal["full", "runner"]] = "full"

    @field_validator("label", mode="before")
    @classmethod
    def sanitize_label(cls, v): return sanitize_identifier(v) if v else ""
