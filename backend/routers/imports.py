import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action
from models import ImportRecord, Engagement, ReconItem, User
from notifications import send_webhook, severity_meets_threshold
from parsers import normalize_to_list, parse_ffuf, parse_httpx, parse_json_or_jsonl, parse_nuclei
from schemas import ToolType
from serializers import serialize_import_record, serialize_engagement

router = APIRouter()

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "2097152"))

ALLOWED_EXTENSIONS = {".json", ".jsonl"}
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/x-ndjson",
    "application/octet-stream",
    "text/plain",
}


def _dedup_recon(
    db: Session,
    incoming: list[ReconItem],
    program_id: str,
    source: str,
) -> tuple[list[ReconItem], int]:
    """Filter incoming recon items down to only those not yet seen for this engagement+source.

    Dedup key: url when present, else host. Sets first_seen_at on each new item.
    Returns (new_items, new_count).
    """
    if not incoming:
        return [], 0

    urls  = [r.url  for r in incoming if r.url]
    hosts = [r.host for r in incoming if r.host and not r.url]

    existing_urls: set[str] = set()
    existing_hosts: set[str] = set()

    if urls:
        existing_urls = set(
            row[0]
            for row in db.query(ReconItem.url).filter(
                ReconItem.program_id == program_id,
                ReconItem.source == source,
                ReconItem.url.in_(urls),
            ).all()
        )

    if hosts:
        existing_hosts = set(
            row[0]
            for row in db.query(ReconItem.host).filter(
                ReconItem.program_id == program_id,
                ReconItem.source == source,
                ReconItem.host.in_(hosts),
                ReconItem.url.is_(None),
            ).all()
        )

    now = datetime.now(timezone.utc)
    new_items = []
    for item in incoming:
        if item.url and item.url in existing_urls:
            continue
        if not item.url and item.host and item.host in existing_hosts:
            continue
        item.first_seen_at = now
        new_items.append(item)

    return new_items, len(new_items)


def _host_of(value: str | None) -> str:
    """Normalize a recon URL or bare hostname down to its host, so a host
    discovered as ``sub.example.com`` and the same host later probed as
    ``https://sub.example.com:443/`` map to one asset. Lowercased; scheme,
    userinfo, port, and path stripped."""
    s = (value or "").strip().lower()
    if not s:
        return ""
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0]   # drop path/query/fragment
    s = s.split("@")[-1]     # drop userinfo
    if s.startswith("["):    # IPv6 literal e.g. [::1]:443
        return s.split("]", 1)[0] + "]"
    return s.split(":", 1)[0]  # drop port


# Live fields an httpx probe enriches on an existing recon row. Only non-empty
# incoming values overwrite, so a re-probe never blanks out an already-set field.
_HTTPX_ENRICH_FIELDS = ("url", "host", "title", "webserver", "port", "tech", "content_type")


def _upsert_recon_httpx(
    db: Session, incoming: list[ReconItem], program_id: str,
) -> tuple[int, int]:
    """Insert genuinely-new httpx hosts and ENRICH existing ones in place — matched
    by normalized host — with live probe data, instead of inserting a duplicate
    blank-ish row. This is what turns a subfinder-discovered host into an enriched
    live row rather than a second entry. Returns (new_count, updated_count)."""
    if not incoming:
        return 0, 0

    by_host: dict[str, ReconItem] = {}
    for row in db.query(ReconItem).filter(
        ReconItem.program_id == program_id,
        ReconItem.source == "httpx",
    ).all():
        h = _host_of(row.host or row.url)
        if h:
            by_host.setdefault(h, row)

    now = datetime.now(timezone.utc)
    new_count = 0
    updated_count = 0
    for item in incoming:
        host = _host_of(item.host or item.url)
        target = by_host.get(host) if host else None
        if target is not None and target is not item:
            for field in _HTTPX_ENRICH_FIELDS:
                value = getattr(item, field)
                if value:
                    setattr(target, field, value)
            if item.status_code is not None:
                target.status_code = item.status_code
            updated_count += 1
        else:
            item.first_seen_at = now
            db.add(item)
            if host:
                by_host[host] = item  # so later rows in this batch enrich, not duplicate
            new_count += 1

    return new_count, updated_count


@router.post("/engagements/{program_id}/imports")
async def import_results(
    program_id: str,
    background_tasks: BackgroundTasks,
    tool_type: ToolType = Form(...),
    file: UploadFile = File(...),
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)

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
    new_count = 0
    updated_count = 0

    if tool_type == "ffuf":
        recon_items = parse_ffuf(items, program_id)
        new_items, new_count = _dedup_recon(db, recon_items, program_id, "ffuf")
        for r in new_items:
            db.add(r)
        imported_count = len(new_items)

    elif tool_type == "httpx":
        recon_items = parse_httpx(items, program_id)
        new_count, updated_count = _upsert_recon_httpx(db, recon_items, program_id)
        imported_count = new_count + updated_count

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
    db.flush()
    log_action(db, current_user["github_id"], "create", "import", record.id, program_id)
    db.commit()

    engagement = db.query(Engagement).filter(Engagement.id == program_id).first()
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()

    # Webhook: new recon assets discovered via httpx
    if tool_type == "httpx" and new_count and user and user.webhook_url:
        message = (
            f"🔍 VardrMap: {new_count} new host(s) discovered for "
            f"{engagement.name if engagement else program_id}"
        )
        background_tasks.add_task(send_webhook, user.webhook_url, message)

    # Webhook: notable nuclei findings at/above the user's severity threshold
    if tool_type == "nuclei" and imported_count and user and user.webhook_url:
        threshold = user.notify_min_severity or "high"
        notable = [s for s in scan_items if severity_meets_threshold(s.severity, threshold)]
        if notable:
            top = max(notable, key=lambda s: ["info", "low", "medium", "high", "critical"].index(s.severity))
            message = (
                f"🚨 VardrMap: {len(notable)} {threshold}+ finding(s) imported for "
                f"{engagement.name if engagement else program_id} — top: [{top.severity}] {top.title or top.template_id}"
            )
            background_tasks.add_task(send_webhook, user.webhook_url, message)

    return {
        "message":       "Import complete",
        "imported_count": imported_count,
        "new_count":      new_count,
        "updated_count":  updated_count,
        "import_record":  serialize_import_record(record),
        "engagement":        serialize_engagement(engagement, db),
    }
