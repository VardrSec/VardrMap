"""Draft VardrGate cases without copying credentials or inferring access policy."""
import copy
import json
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import ApiEndpoint, AuthorizationTestCase
from routers.test_cases import TestCaseCreate, _validate_spec, serialize_test_case
from security import strip_html

router = APIRouter(tags=["test_cases"])
METHODS = {"get", "head", "post", "put", "patch", "delete", "options", "trace"}


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint_ids: list[str] = Field(default_factory=list, max_length=100)
    openapi: dict | None = None
    base_url: str = Field(default="", max_length=2000)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ReviewedCases(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed: Literal[True]
    cases: list[TestCaseCreate] = Field(min_length=1, max_length=100)


def _base_url(value):
    if not isinstance(value, str):
        raise HTTPException(400, "Provide an absolute HTTP(S) base_url")
    try:
        url = urlsplit(value)
        valid = url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password and not url.query and not url.fragment and not re.search(r"[\s{}]", value)
        _ = url.port
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(400, "Provide an absolute HTTP(S) base_url without credentials, query parameters, or variables")
    return value.rstrip("/")


def _openapi_operations(document, override):
    if len(json.dumps(document).encode()) > 2 * 1024 * 1024:
        raise HTTPException(413, "OpenAPI document exceeds 2 MiB")
    if not str(document.get("openapi", "")).startswith("3."):
        raise HTTPException(400, "Use an OpenAPI 3.x JSON document")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise HTTPException(400, "OpenAPI paths must be an object")
    operations = []
    for path, item in paths.items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(item, dict):
            raise HTTPException(400, "OpenAPI paths must contain path-item objects")
        if "$ref" in item:
            raise HTTPException(400, "Resolve path-item references locally before previewing; references are never fetched")
        for method, operation in item.items():
            if method not in METHODS:
                continue
            if not isinstance(operation, dict) or "$ref" in operation:
                raise HTTPException(400, "Operations must be inline objects")
            servers = operation.get("servers", item.get("servers", document.get("servers", [])))
            server = servers[0].get("url", "") if isinstance(servers, list) and servers and isinstance(servers[0], dict) else ""
            base = _base_url(override or server)
            # Examples, query strings, bodies, headers and security values are
            # intentionally not copied from potentially credential-bearing input.
            if "?" in path or "#" in path or re.search(r"[\s]", path):
                raise HTTPException(400, "OpenAPI paths cannot contain queries, fragments, or whitespace")
            operations.append((method.upper(), base + path, "openapi"))
    return operations


def _draft(method, url, source):
    identities = [
        {"id": "anonymous", "credential": {"type": "static_header", "header": "", "value": ""}},
        {"id": "member", "credential": {"type": "bearer", "value_env": "VARDRGATE_MEMBER_TOKEN"}},
    ]
    return {
        "name": f"{method} {urlsplit(url).path}"[:200],
        "description": f"Draft from {source}; review URL, identities, request body and access decisions before saving.",
        "spec": {"id": f"case-{uuid4()}", "request": {"method": method, "url": url},
                 "mutating": method in {"POST", "PUT", "PATCH", "DELETE"}, "identities": identities,
                 "expected_access": [{"identity_id": i["id"], "decision": "skip"} for i in identities]},
    }


@router.post("/engagements/{program_id}/test-cases/preview")
def preview_cases(program_id: str, body: DraftRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    get_engagement_or_404(program_id, current_user, db)
    if bool(body.endpoint_ids) == (body.openapi is not None):
        raise HTTPException(400, "Choose selected endpoint_ids or an OpenAPI document")
    if body.openapi is not None:
        operations = _openapi_operations(body.openapi, body.base_url)
    else:
        ids = set(body.endpoint_ids)
        rows = db.query(ApiEndpoint).filter(ApiEndpoint.program_id == program_id, ApiEndpoint.id.in_(ids)).order_by(ApiEndpoint.method, ApiEndpoint.host, ApiEndpoint.path_template, ApiEndpoint.id).all()
        if len(rows) != len(ids):
            raise HTTPException(404, "Endpoint not found")
        operations = []
        for row in rows:
            host = f"[{row.host}]" if ":" in row.host and not row.host.startswith("[") else row.host
            port = f":{row.port}" if row.port else ""
            base = _base_url(body.base_url or f"{row.scheme}://{host}{port}")
            operations.append((row.method, base + row.path_template, "observed API operation"))
    page = operations[body.offset:body.offset + body.limit]
    end = body.offset + len(page)
    return {"drafts": [_draft(*op) for op in page], "total": len(operations), "offset": body.offset, "limit": body.limit, "next_offset": end if end < len(operations) else None,
            "review_notes": ["No cases have been stored or queued.", "Replace path variables and review request bodies for mutating operations.", "Set identity secret references and decide expected access; observed responses do not determine authorization policy."]}


@router.post("/engagements/{program_id}/test-cases/reviewed", status_code=201)
def save_reviewed_cases(program_id: str, body: ReviewedCases, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    rows = []
    for case in body.cases:
        spec = _validate_spec(copy.deepcopy(case.spec))
        url = spec["request"]["url"]
        try:
            parts = urlsplit(url)
            valid = parts.scheme in {"http", "https"} and parts.hostname and not parts.username and not parts.password and not parts.fragment and not re.search(r"[{}\s]", url)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise HTTPException(400, "Review each request URL: supply a concrete HTTP(S) URL without credentials or unresolved variables")
        expected = spec.get("expected_access") or []
        ids = {i["id"] for i in spec["identities"]}
        if len(expected) != len(ids) or {e["identity_id"] for e in expected} != ids or not any(e["decision"] != "skip" for e in expected):
            raise HTTPException(400, "Review exactly one access decision per identity, including at least one allow or deny")
        if not case.name.strip():
            raise HTTPException(400, "Case name is required")
        row = AuthorizationTestCase(program_id=program_id, owner_github_id=current_user["github_id"], name=case.name, description=strip_html(case.description or ""), test_case_id=str(spec["id"])[:200], spec=spec)
        db.add(row)
        rows.append(row)
    db.flush()
    for row in rows:
        log_action(db, current_user["github_id"], "review_create", "test_case", row.id, program_id)
    db.commit()
    return {"test_cases": [serialize_test_case(row) for row in rows]}
