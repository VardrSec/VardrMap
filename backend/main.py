import json
import os
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
import re
import bleach

from db import Base, engine, get_db
from models import (
    Finding,
    ImportRecord,
    ManualTest,
    Program,
    ReconItem,
    Report,
    ScanItem,
    ScopeItem,
    User,
)

# -----------------------------------------------------------------------------
# Create tables on startup
# -----------------------------------------------------------------------------

Base.metadata.create_all(bind=engine)

# -----------------------------------------------------------------------------
# Environment config
# -----------------------------------------------------------------------------

ENV = os.getenv("ENV") or os.getenv("RAILWAY_ENVIRONMENT_NAME", "development")
BACKEND_JWT_SECRET = os.getenv("BACKEND_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "2097152"))

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,https://vardr-map.vercel.app",
    ).split(",")
    if origin.strip()
]

ALLOWED_EXTENSIONS = {".json", ".jsonl"}
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/x-ndjson",
    "application/octet-stream",
    "text/plain",
}

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------

app = FastAPI(title="VardrMap API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# -----------------------------------------------------------------------------
# Enums / strict types
# -----------------------------------------------------------------------------

Severity = Literal["info", "low", "medium", "high", "critical"]
FindingStatus = Literal["new", "candidate", "triaged", "in_progress", "closed"]
ManualStatus = Literal["new", "in_progress", "validated", "closed"]
ScopeKind = Literal["domain", "subdomain", "url", "cidr", "api", "mobile"]
ReportStatus = Literal["draft", "submitted", "accepted", "duplicate", "informative", "resolved"]
ToolType = Literal["ffuf", "httpx", "nuclei"]

# -----------------------------------------------------------------------------
# ✦ INPUT SANITIZATION
#
# Strategy (order matters):
#   1. Null byte removal
#   2. Detect injection patterns on the RAW input (before any stripping)
#      This prevents obfuscated payloads like <scr<script>ipt> bypassing
#      regex-based detection by stripping first.
#   3. Strip all HTML using bleach (proper parser, not regex)
#      bleach handles nested/malformed tags that fool simple regex.
#
# Short fields (name, title, asset): detect then strip, reject on match.
# Long fields (summary, steps, markdown): strip only, no rejection
#   — allows markdown syntax like **bold** and `code` safely.
# -----------------------------------------------------------------------------

# Raw injection patterns — checked BEFORE any stripping
# Covers script tags, event handlers, javascript: URIs, data URIs
_INJECT_RE = re.compile(
    r"""(
        <script           |  # script tags
        <iframe           |  # iframe injection
        <object           |  # object/embed
        <embed            |
        <svg              |  # SVG-based XSS
        <img              |  # img onerror
        javascript\s*:    |  # javascript: URI
        data\s*:.*text/html  # data URI XSS
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# Event handler attributes — also checked on raw input
_EVENT_HANDLER_RE = re.compile(r'on\w+\s*=', re.IGNORECASE)


def _remove_null_bytes(value: str) -> str:
    return value.replace(chr(0), "")


def strip_html(value: str | None) -> str:
    """Strip all HTML tags using bleach. Safe for long-form markdown fields.
    Allows no tags at all — markdown syntax (**, `code`, #) is plain text
    and passes through untouched. bleach handles obfuscated/nested tags
    that fool regex-based strippers.
    """
    if not value:
        return value or ""
    value = _remove_null_bytes(value)
    # bleach.clean with no allowed tags strips everything
    return bleach.clean(value, tags=[], attributes={}, strip=True).strip()


def sanitize_identifier(value: str | None) -> str:
    """Strict sanitizer for short identifier fields: name, title, asset.

    Detection runs on RAW input before stripping — this catches obfuscated
    payloads like <scr<script>ipt> that survive naive regex stripping first.
    After detection, bleach strips any remaining tags.
    """
    if not value:
        return value or ""
    raw = _remove_null_bytes(value)

    # ✦ Detect on raw input FIRST — before any stripping
    if _INJECT_RE.search(raw) or _EVENT_HANDLER_RE.search(raw):
        raise ValueError("Invalid characters in field")

    # Strip any remaining HTML with bleach
    return bleach.clean(raw, tags=[], attributes={}, strip=True).strip()


# -----------------------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------------------

class ProgramCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    platform: Optional[str] = Field(default="", max_length=80)
    program_url: Optional[str] = Field(default="", max_length=500)
    scope_summary: Optional[str] = Field(default="", max_length=5000)
    severity_guidance: Optional[str] = Field(default="", max_length=5000)
    safe_harbor_notes: Optional[str] = Field(default="", max_length=5000)

    # ✦ SANITIZATION VALIDATORS
    @field_validator("name", "platform", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v)

    @field_validator("program_url", "scope_summary", "severity_guidance", "safe_harbor_notes", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v)


class ProgramUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    platform: Optional[str] = Field(default=None, max_length=80)
    program_url: Optional[str] = Field(default=None, max_length=500)
    scope_summary: Optional[str] = Field(default=None, max_length=5000)
    severity_guidance: Optional[str] = Field(default=None, max_length=5000)
    safe_harbor_notes: Optional[str] = Field(default=None, max_length=5000)

    # ✦ SANITIZATION VALIDATORS
    @field_validator("name", "platform", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v) if v else v

    @field_validator("program_url", "scope_summary", "severity_guidance", "safe_harbor_notes", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v) if v else v


class ScopeItemCreate(BaseModel):
    value: str = Field(min_length=1, max_length=500)
    kind: ScopeKind = "domain"
    notes: Optional[str] = Field(default="", max_length=2000)

    # ✦ SANITIZATION VALIDATORS
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

    # ✦ SANITIZATION VALIDATORS
    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v): return sanitize_identifier(v)

    @field_validator("hypothesis", "evidence", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v)
    # payload intentionally not stripped — users paste raw HTTP/code here


class FindingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    severity: Severity = "info"
    asset: Optional[str] = Field(default="", max_length=500)
    status: FindingStatus = "new"
    summary: Optional[str] = Field(default="", max_length=5000)
    steps: Optional[str] = Field(default="", max_length=10000)
    impact: Optional[str] = Field(default="", max_length=5000)
    remediation: Optional[str] = Field(default="", max_length=5000)

    # ✦ SANITIZATION VALIDATORS
    @field_validator("title", "asset", mode="before")
    @classmethod
    def sanitize_short(cls, v): return sanitize_identifier(v) if v else v

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
    def sanitize_short(cls, v): return sanitize_identifier(v) if v else v

    @field_validator("summary", "steps", "impact", "remediation", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v) if v else v


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

    # ✦ SANITIZATION VALIDATORS
    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v): return sanitize_identifier(v)

    @field_validator("summary", "steps", "impact", "remediation", "cwe", "cvss", mode="before")
    @classmethod
    def sanitize_long(cls, v): return strip_html(v)

# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------

def serialize_scope_item(item: ScopeItem) -> dict:
    return {
        "id": item.id,
        "value": item.value,
        "kind": item.kind,
        "notes": item.notes or "",
    }


def serialize_manual_test(t: ManualTest) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "hypothesis": t.hypothesis or "",
        "payload": t.payload or "",
        "evidence": t.evidence or "",
        "status": t.status,
    }


def serialize_finding(f: Finding) -> dict:
    return {
        "id": f.id,
        "title": f.title,
        "severity": f.severity,
        "asset": f.asset or "",
        "status": f.status,
        "summary": f.summary or "",
        "steps": f.steps or "",
        "impact": f.impact or "",
        "remediation": f.remediation or "",
    }


def serialize_report(r: Report) -> dict:
    return {
        "id": r.id,
        "finding_id": r.finding_id or "",
        "title": r.title,
        "summary": r.summary or "",
        "steps": r.steps or "",
        "impact": r.impact or "",
        "remediation": r.remediation or "",
        "cwe": r.cwe or "",
        "cvss": r.cvss or "",
        "status": r.status,
    }


def serialize_recon_item(item: ReconItem) -> dict:
    tech_list = [t for t in (item.tech or "").split(",") if t]
    return {
        "id": item.id,
        "source": item.source or "",
        "url": item.url or "",
        "path": item.path or "",
        "host": item.host or "",
        "title": item.title or "",
        "status_code": item.status_code,
        "webserver": item.webserver or "",
        "port": item.port or "",
        "tech": tech_list,
        "content_type": item.content_type or "",
        "length": item.length,
        "words": item.words,
        "lines": item.lines,
        "notes": item.notes or "",
    }


def serialize_scan_item(item: ScanItem) -> dict:
    return {
        "id": item.id,
        "source": item.source or "nuclei",
        "template_id": item.template_id or "",
        "title": item.title or "",
        "severity": item.severity or "info",
        "asset": item.asset or "",
        "matched_at": item.matched_at or "",
        "type": item.type or "",
        "description": item.description or "",
        "status": item.status or "new",
        "cwe": item.cwe or "",
        "cvss": item.cvss or "",
    }


def serialize_import_record(r: ImportRecord) -> dict:
    return {
        "id": r.id,
        "tool_type": r.tool_type or "",
        "filename": r.filename or "redacted",
        "imported_count": r.imported_count or 0,
    }


def serialize_program(p: Program, db: Session) -> dict:
    recon_count = db.query(ReconItem).filter(ReconItem.program_id == p.id).count()
    scans_count = db.query(ScanItem).filter(ScanItem.program_id == p.id).count()
    return {
        "id": p.id,
        "owner_github_id": p.owner_github_id,
        "name": p.name,
        "platform": p.platform or "",
        "program_url": p.program_url or "",
        "scope_summary": p.scope_summary or "",
        "severity_guidance": p.severity_guidance or "",
        "safe_harbor_notes": p.safe_harbor_notes or "",
        "scope": {
            "in": [serialize_scope_item(i) for i in p.scope_items if i.scope_type == "in"],
            "out": [serialize_scope_item(i) for i in p.scope_items if i.scope_type == "out"],
        },
        "imports": [serialize_import_record(r) for r in p.import_records],
        "recon_count": recon_count,
        "scans_count": scans_count,
        "manual_tests": [serialize_manual_test(t) for t in p.manual_tests],
        "findings": [serialize_finding(f) for f in p.findings],
        "reports": [serialize_report(r) for r in p.reports],
    }

# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------

# Auth flow: GitHub OAuth is handled entirely by NextAuth on the frontend.
# After sign-in, NextAuth mints a short-lived JWT (signed with BACKEND_JWT_SECRET)
# that includes the GitHub user's ID, username, and email. Every request from
# the frontend carries that token in the Authorization header, and this function
# verifies it. The backend never talks to GitHub directly.
def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not BACKEND_JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server auth not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.split(" ", 1)[1].strip()

    try:
        payload = jwt.decode(
            token,
            BACKEND_JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience="vardrmap-backend",
            issuer="vardrmap-frontend",
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Unauthorized")

    github_id = payload.get("sub")
    if not github_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return {
        "github_id": str(github_id),
        "username": str(payload.get("username", "")),
        "email": str(payload.get("email", "")),
    }


def get_program_or_404(program_id: str, current_user: dict[str, str], db: Session) -> Program:
    program = (
        db.query(Program)
        .filter(
            Program.id == program_id,
            Program.owner_github_id == current_user["github_id"],
        )
        .first()
    )
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    return program

# -----------------------------------------------------------------------------
# Import parsers
# -----------------------------------------------------------------------------

# Try JSONL first (newline-delimited, what most tools produce with -jsonl flags),
# then fall back to a single JSON object/array. Both formats are common in the wild.
def parse_json_or_jsonl(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if "\n" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        try:
            return [json.loads(line) for line in lines]
        except json.JSONDecodeError:
            pass  # not valid JSONL, fall through and try as a single JSON blob

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON/JSONL: {exc.msg}")


# Different tools wrap their output differently — ffuf wraps results under a
# "results" key, httpx and nuclei emit a bare array, and sometimes a single-run
# output is just one object. This flattens all three into the same list shape.
def normalize_to_list(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        if isinstance(parsed.get("results"), list):
            return [item for item in parsed["results"] if isinstance(item, dict)]
        return [parsed]
    raise HTTPException(status_code=400, detail="Unsupported JSON structure")


def parse_ffuf(items: list[dict[str, Any]], program_id: str) -> list[ReconItem]:
    out = []
    for item in items:
        url = item.get("url") or item.get("input", {}).get("FUZZ") or ""
        out.append(ReconItem(
            program_id=program_id,
            source="ffuf",
            url=url,
            path=str(item.get("input", {}).get("FUZZ", "")),
            status_code=item.get("status"),
            length=item.get("length"),
            words=item.get("words"),
            lines=item.get("lines"),
            content_type=item.get("content-type") or item.get("content_type") or "",
        ))
    return out


def parse_httpx(items: list[dict[str, Any]], program_id: str) -> list[ReconItem]:
    out = []
    for item in items:
        tech_value = item.get("tech") or item.get("technologies") or []
        tech_str = ",".join(str(t) for t in tech_value) if isinstance(tech_value, list) else str(tech_value or "")
        out.append(ReconItem(
            program_id=program_id,
            source="httpx",
            url=item.get("url") or "",
            host=item.get("host") or "",
            title=item.get("title") or "",
            status_code=item.get("status-code") or item.get("status_code"),
            webserver=item.get("webserver") or "",
            port=str(item.get("port") or ""),
            tech=tech_str,
            content_type=item.get("content-type") or item.get("content_type") or "",
        ))
    return out


def parse_nuclei(items: list[dict[str, Any]], program_id: str) -> list[ScanItem]:
    out = []
    for item in items:
        info = item.get("info") if isinstance(item.get("info"), dict) else {}
        classification = info.get("classification") if isinstance(info.get("classification"), dict) else {}
        out.append(ScanItem(
            program_id=program_id,
            source="nuclei",
            template_id=item.get("template-id") or item.get("templateID") or "",
            title=info.get("name") or item.get("matcher-name") or "Untitled Finding",
            severity=info.get("severity") or "info",
            asset=item.get("matched-at") or item.get("host") or "",
            matched_at=item.get("matched-at") or "",
            type=item.get("type") or "",
            description=info.get("description") or "",
            status="new",
            cwe=classification.get("cwe-id") or "",
            cvss=str(classification.get("cvss-score") or ""),
        ))
    return out

# -----------------------------------------------------------------------------
# Public routes
# -----------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"message": "VardrMap API is running", "environment": ENV}


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": ENV}


@app.get("/me")
def me(current_user: dict[str, str] = Depends(get_current_user)):
    return current_user

# -----------------------------------------------------------------------------
# Auth sync — upserts user record on login (called once by frontend)
# -----------------------------------------------------------------------------

@app.post("/auth/sync")
def auth_sync(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if user:
        # Update username/email in case they changed on GitHub
        user.username = current_user["username"]
        user.email = current_user["email"]
    else:
        user = User(
            github_id=current_user["github_id"],
            username=current_user["username"],
            email=current_user["email"],
        )
        db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "github_id": user.github_id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }

# -----------------------------------------------------------------------------
# Programs
# -----------------------------------------------------------------------------

@app.get("/programs")
def get_programs(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(Program).filter(Program.owner_github_id == current_user["github_id"]).all()
    return {"programs": [serialize_program(p, db) for p in rows]}


@app.post("/programs")
def create_program(
    payload: ProgramCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ensure user row exists before creating program (FK safety)
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if not user:
        user = User(
            github_id=current_user["github_id"],
            username=current_user["username"],
            email=current_user["email"],
        )
        db.add(user)
        db.flush()

    program = Program(
        owner_github_id=current_user["github_id"],
        name=payload.name,
        platform=payload.platform or "",
        program_url=payload.program_url or "",
        scope_summary=payload.scope_summary or "",
        severity_guidance=payload.severity_guidance or "",
        safe_harbor_notes=payload.safe_harbor_notes or "",
    )
    db.add(program)
    db.commit()
    db.refresh(program)
    return serialize_program(program, db)


@app.get("/programs/{program_id}")
def get_program(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    return serialize_program(program, db)


@app.patch("/programs/{program_id}")
def update_program(
    program_id: str,
    payload: ProgramUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(program, key, value)
    db.commit()
    db.refresh(program)
    return serialize_program(program, db)


@app.delete("/programs/{program_id}")
def delete_program(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    db.delete(program)
    db.commit()
    return {"message": "Program deleted"}

# -----------------------------------------------------------------------------
# Scope
# -----------------------------------------------------------------------------

@app.post("/programs/{program_id}/scope/in")
def add_in_scope_item(
    program_id: str,
    payload: ScopeItemCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    item = ScopeItem(
        program_id=program_id,
        scope_type="in",
        value=payload.value,
        kind=payload.kind,
        notes=payload.notes or "",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return serialize_scope_item(item)


@app.post("/programs/{program_id}/scope/out")
def add_out_scope_item(
    program_id: str,
    payload: ScopeItemCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    item = ScopeItem(
        program_id=program_id,
        scope_type="out",
        value=payload.value,
        kind=payload.kind,
        notes=payload.notes or "",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return serialize_scope_item(item)


@app.delete("/programs/{program_id}/scope/{scope_type}/{item_id}")
def delete_scope_item(
    program_id: str,
    scope_type: str,
    item_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if scope_type not in ["in", "out"]:
        raise HTTPException(status_code=400, detail="Invalid scope type")
    get_program_or_404(program_id, current_user, db)
    item = db.query(ScopeItem).filter(
        ScopeItem.id == item_id,
        ScopeItem.program_id == program_id,
        ScopeItem.scope_type == scope_type,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scope item not found")
    db.delete(item)
    db.commit()
    return {"message": "Scope item deleted"}

# -----------------------------------------------------------------------------
# Recon / scans
# -----------------------------------------------------------------------------

@app.get("/programs/{program_id}/recon")
def get_recon(
    program_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    total = db.query(ReconItem).filter(ReconItem.program_id == program_id).count()
    items = db.query(ReconItem).filter(ReconItem.program_id == program_id).offset(offset).limit(limit).all()
    return {"recon": [serialize_recon_item(r) for r in items], "total": total, "offset": offset, "limit": limit}


@app.get("/programs/{program_id}/scans")
def get_scans(
    program_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    total = db.query(ScanItem).filter(ScanItem.program_id == program_id).count()
    items = db.query(ScanItem).filter(ScanItem.program_id == program_id).offset(offset).limit(limit).all()
    return {"scans": [serialize_scan_item(s) for s in items], "total": total, "offset": offset, "limit": limit}

# -----------------------------------------------------------------------------
# Manual tests
# -----------------------------------------------------------------------------

@app.get("/programs/{program_id}/manual-tests")
def get_manual_tests(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    return {"manual_tests": [serialize_manual_test(t) for t in program.manual_tests]}


@app.post("/programs/{program_id}/manual-tests")
def add_manual_test(
    program_id: str,
    payload: ManualTestCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    test = ManualTest(
        program_id=program_id,
        title=payload.title,
        hypothesis=payload.hypothesis or "",
        payload=payload.payload or "",
        evidence=payload.evidence or "",
        status=payload.status,
    )
    db.add(test)
    db.commit()
    db.refresh(test)
    return serialize_manual_test(test)


@app.delete("/programs/{program_id}/manual-tests/{test_id}")
def delete_manual_test(
    program_id: str,
    test_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    test = db.query(ManualTest).filter(
        ManualTest.id == test_id,
        ManualTest.program_id == program_id,
    ).first()
    if not test:
        raise HTTPException(status_code=404, detail="Manual test not found")
    db.delete(test)
    db.commit()
    return {"message": "Manual test deleted"}

# -----------------------------------------------------------------------------
# Findings
# -----------------------------------------------------------------------------

@app.get("/programs/{program_id}/findings")
def get_findings(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    return {"findings": [serialize_finding(f) for f in program.findings]}


@app.post("/programs/{program_id}/findings")
def add_finding(
    program_id: str,
    payload: FindingCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    finding = Finding(
        program_id=program_id,
        title=payload.title,
        severity=payload.severity,
        asset=payload.asset or "",
        status=payload.status,
        summary=payload.summary or "",
        steps=payload.steps or "",
        impact=payload.impact or "",
        remediation=payload.remediation or "",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding)


@app.patch("/programs/{program_id}/findings/{finding_id}")
def update_finding(
    program_id: str,
    finding_id: str,
    payload: FindingUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.program_id == program_id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(finding, key, value)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding)


@app.delete("/programs/{program_id}/findings/{finding_id}")
def delete_finding(
    program_id: str,
    finding_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.program_id == program_id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    db.delete(finding)
    db.commit()
    return {"message": "Finding deleted"}

# -----------------------------------------------------------------------------
# Reports
# -----------------------------------------------------------------------------

@app.get("/programs/{program_id}/reports")
def get_reports(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    return {"reports": [serialize_report(r) for r in program.reports]}


@app.post("/programs/{program_id}/reports")
def add_report(
    program_id: str,
    payload: ReportCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    report = Report(
        program_id=program_id,
        finding_id=payload.finding_id or "",
        title=payload.title,
        summary=payload.summary or "",
        steps=payload.steps or "",
        impact=payload.impact or "",
        remediation=payload.remediation or "",
        cwe=payload.cwe or "",
        cvss=payload.cvss or "",
        status=payload.status,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return serialize_report(report)


@app.delete("/programs/{program_id}/reports/{report_id}")
def delete_report(
    program_id: str,
    report_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    report = db.query(Report).filter(
        Report.id == report_id,
        Report.program_id == program_id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    db.delete(report)
    db.commit()
    return {"message": "Report deleted"}

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

@app.post("/programs/{program_id}/imports")
async def import_results(
    program_id: str,
    tool_type: ToolType = Form(...),
    file: UploadFile = File(...),
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .json and .jsonl files are allowed")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    parsed = parse_json_or_jsonl(raw)
    items = normalize_to_list(parsed)
    imported_count = 0

    if tool_type == "ffuf":
        recon_items = parse_ffuf(items, program_id)
        for r in recon_items:
            db.add(r)
        imported_count = len(recon_items)
    elif tool_type == "httpx":
        recon_items = parse_httpx(items, program_id)
        for r in recon_items:
            db.add(r)
        imported_count = len(recon_items)
    elif tool_type == "nuclei":
        scan_items = parse_nuclei(items, program_id)
        for s in scan_items:
            db.add(s)
        imported_count = len(scan_items)

    # Store "redacted" instead of the real filename — the original file path
    # often leaks local directory structure and isn't useful after import anyway.
    record = ImportRecord(
        program_id=program_id,
        tool_type=tool_type,
        filename="redacted",
        imported_count=imported_count,
    )
    db.add(record)
    db.commit()

    program = db.query(Program).filter(Program.id == program_id).first()
    return {
        "message": "Import complete",
        "import_record": serialize_import_record(record),
        "program": serialize_program(program, db),
    }
