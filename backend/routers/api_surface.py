"""Burp-assisted API surface inventory and redacted exchange capture."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import redaction
from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import ApiEndpoint, ApiExchange
from security import sanitize_identifier, strip_html

router = APIRouter(tags=["api-surface"])
MAX_MESSAGE_CHARS = 200_000
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"}
TOOLS = {"proxy", "repeater", "intruder", "scanner", "organizer", "unknown"}

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
_INTEGER = re.compile(r"^\d+$")
_OPAQUE = re.compile(r"^(?:[a-z]{2,12}_)?[A-Za-z0-9_-]{16,}$")


class ExchangeCreate(BaseModel):
    method: str = Field(max_length=10)
    url: str = Field(max_length=4000)
    path_template: str | None = Field(default=None, max_length=1000)
    source_tool: str = Field(default="unknown", max_length=30)
    identity_label: str = Field(default="anonymous", max_length=100)
    request_headers: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    request_body: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    response_headers: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    response_body: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    response_status: int | None = Field(default=None, ge=100, le=599)
    response_length: int | None = Field(default=None, ge=0)
    response_mime: str = Field(default="", max_length=100)
    response_time_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    note: str = Field(default="", max_length=1000)
    captured_at: datetime | None = None

    @field_validator("method", mode="before")
    @classmethod
    def uppercase_method(cls, value):
        return str(value).upper()

    @field_validator("identity_label", "response_mime", mode="before")
    @classmethod
    def clean_label(cls, value):
        return sanitize_identifier(value) if value else ""


def infer_path_template(path: str) -> str:
    """Collapse common identifier-shaped segments without discarding route shape."""
    parts = []
    for segment in (path or "/").split("/"):
        if _UUID.fullmatch(segment):
            parts.append("{uuid}")
        elif _INTEGER.fullmatch(segment):
            parts.append("{id}")
        elif _OPAQUE.fullmatch(segment):
            parts.append("{opaque_id}")
        else:
            parts.append(segment)
    result = "/".join(parts)
    return result if result.startswith("/") else f"/{result}"


def _parameter_names(body: str) -> list[str]:
    if not body:
        return []
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return []
    names: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                names.add(str(key)[:100])
                walk(value)
        elif isinstance(node, list):
            for value in node[:50]:
                walk(value)

    walk(parsed)
    return sorted(names)[:200]


def _exchange_dict(row: ApiExchange) -> dict:
    return {
        "id": row.id, "endpoint_id": row.endpoint_id, "source_tool": row.source_tool,
        "identity_label": row.identity_label, "request_headers": row.request_headers,
        "request_body": row.request_body, "response_headers": row.response_headers,
        "response_body": row.response_body, "request_hash": row.request_hash,
        "response_hash": row.response_hash, "response_status": row.response_status,
        "response_length": row.response_length, "response_mime": row.response_mime,
        "response_time_ms": row.response_time_ms, "parameter_names": row.parameter_names or [],
        "note": row.note, "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _endpoint_dict(row: ApiEndpoint, include_exchanges: bool = False, exchanges=None) -> dict:
    exchanges = row.exchanges if exchanges is None else exchanges
    result = {
        "id": row.id, "program_id": row.program_id, "method": row.method,
        "scheme": row.scheme, "host": row.host, "port": row.port,
        "path_template": row.path_template, "source": row.source, "notes": row.notes,
        "observation_count": row.observation_count,
        "statuses": sorted({x.response_status for x in exchanges if x.response_status is not None}),
        "identities": sorted({x.identity_label for x in exchanges}),
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
    }
    if include_exchanges:
        result["exchanges"] = [_exchange_dict(x) for x in sorted(exchanges, key=lambda x: x.created_at, reverse=True)]
    return result


@router.post("/engagements/{program_id}/api/exchanges", status_code=201)
def create_exchange(program_id: str, payload: ExchangeCreate, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    if payload.method not in METHODS:
        raise HTTPException(status_code=400, detail="Unsupported HTTP method")
    if payload.source_tool not in TOOLS:
        raise HTTPException(status_code=400, detail=f"source_tool must be one of {sorted(TOOLS)}")
    parsed = urlsplit(payload.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="url must be an absolute HTTP(S) URL")

    template = payload.path_template or infer_path_template(parsed.path)
    if not template.startswith("/") or "?" in template or "#" in template:
        raise HTTPException(status_code=400, detail="path_template must be an absolute path without query or fragment")
    host = parsed.hostname.lower()
    canonical = f"{parsed.scheme}://{host}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}{template}"
    endpoint = db.query(ApiEndpoint).filter(
        ApiEndpoint.program_id == program_id,
        ApiEndpoint.method == payload.method,
        ApiEndpoint.canonical_key == canonical,
    ).first()
    now = datetime.now(timezone.utc)
    if not endpoint:
        try:
            with db.begin_nested():
                endpoint = ApiEndpoint(program_id=program_id, method=payload.method, scheme=parsed.scheme,
                                       host=host, port=parsed.port, path_template=template,
                                       canonical_key=canonical, source="burp", first_seen_at=now, last_seen_at=now)
                db.add(endpoint)
                db.flush()
        except IntegrityError:
            # Another Burp promotion created the same operation between our
            # lookup and insert. Reuse it instead of turning a benign race into
            # a 500 response.
            endpoint = db.query(ApiEndpoint).filter(
                ApiEndpoint.program_id == program_id,
                ApiEndpoint.method == payload.method,
                ApiEndpoint.canonical_key == canonical,
            ).one()

    request_headers = redaction.redact_text(payload.request_headers)
    request_body = redaction.redact_text(payload.request_body)
    response_headers = redaction.redact_text(payload.response_headers)
    response_body = redaction.redact_text(payload.response_body)
    row = ApiExchange(
        program_id=program_id, endpoint_id=endpoint.id, source_tool=payload.source_tool,
        identity_label=payload.identity_label or "anonymous", request_headers=request_headers,
        request_body=request_body, response_headers=response_headers, response_body=response_body,
        request_hash=hashlib.sha256((request_headers + "\n\n" + request_body).encode()).hexdigest(),
        response_hash=hashlib.sha256((response_headers + "\n\n" + response_body).encode()).hexdigest(),
        response_status=payload.response_status, response_length=payload.response_length,
        response_mime=payload.response_mime, response_time_ms=payload.response_time_ms,
        parameter_names=_parameter_names(request_body), note=strip_html(payload.note),
        captured_at=payload.captured_at or now,
    )
    db.add(row)
    db.flush()
    db.execute(
        update(ApiEndpoint)
        .where(ApiEndpoint.id == endpoint.id)
        .values(
            observation_count=ApiEndpoint.observation_count + 1,
            last_seen_at=now,
        )
    )
    log_action(db, current_user["github_id"], "create", "api_exchange", row.id, program_id)
    db.commit()
    db.refresh(endpoint)
    db.refresh(row)
    return {"endpoint": _endpoint_dict(endpoint), "exchange": _exchange_dict(row)}


@router.get("/engagements/{program_id}/api/endpoints")
def list_endpoints(program_id: str, search: str = Query(default="", max_length=200), method: str = Query(default="", max_length=10), limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    get_engagement_or_404(program_id, current_user, db)
    query = db.query(ApiEndpoint).filter(ApiEndpoint.program_id == program_id)
    if method:
        query = query.filter(ApiEndpoint.method == method.upper())
    if search:
        term = f"%{search}%"
        query = query.filter(or_(ApiEndpoint.host.ilike(term), ApiEndpoint.path_template.ilike(term)))
    total = query.count()
    rows = query.order_by(ApiEndpoint.last_seen_at.desc()).offset(offset).limit(limit).all()
    endpoint_ids = [row.id for row in rows]
    summaries: dict[str, list[ApiExchange]] = {endpoint_id: [] for endpoint_id in endpoint_ids}
    if endpoint_ids:
        # Fetch metadata only. Request/response bodies can be large and have no
        # place in the inventory query; they are loaded only for one detail view.
        for exchange in db.query(
            ApiExchange.endpoint_id, ApiExchange.response_status, ApiExchange.identity_label
        ).filter(ApiExchange.endpoint_id.in_(endpoint_ids)).all():
            summaries[exchange.endpoint_id].append(exchange)
    return {"endpoints": [_endpoint_dict(row, exchanges=summaries[row.id]) for row in rows], "total": total}


@router.get("/engagements/{program_id}/api/endpoints/{endpoint_id}")
def get_endpoint(program_id: str, endpoint_id: str, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    get_engagement_or_404(program_id, current_user, db)
    row = db.query(ApiEndpoint).filter(ApiEndpoint.id == endpoint_id, ApiEndpoint.program_id == program_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="API endpoint not found")
    exchange_query = db.query(ApiExchange).filter(ApiExchange.endpoint_id == endpoint_id)
    exchange_total = exchange_query.count()
    exchanges = exchange_query.order_by(ApiExchange.created_at.desc()).offset(offset).limit(limit).all()
    result = _endpoint_dict(row, include_exchanges=True, exchanges=exchanges)
    result["exchange_total"] = exchange_total
    return result


@router.delete("/engagements/{program_id}/api/exchanges/{exchange_id}")
def delete_exchange(program_id: str, exchange_id: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    row = db.query(ApiExchange).filter(ApiExchange.id == exchange_id, ApiExchange.program_id == program_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="API exchange not found")
    endpoint = row.endpoint
    db.delete(row)
    endpoint.observation_count = max(0, endpoint.observation_count - 1)
    log_action(db, current_user["github_id"], "delete", "api_exchange", exchange_id, program_id)
    db.commit()
    return {"message": "API exchange deleted"}
