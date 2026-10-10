import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

import assets as asset_graph
import provenance
from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import ImportRecord, Engagement, ReconItem, ScanItem, User
from notifications import send_webhook, severity_meets_threshold
from parsers import (
    normalize_to_list,
    parse_dalfox,
    parse_ffuf,
    parse_gau,
    parse_httpx,
    parse_json_or_jsonl,
    parse_katana,
    parse_nuclei,
)
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


def _link_one(db, program_id: str, row, source: str) -> None:
    """Attach a single row to its asset. Idempotent; skips rows already linked."""
    if row is None or getattr(row, "asset_id", None):
        return
    observed = getattr(row, "url", "") or getattr(row, "host", "") or getattr(row, "asset", "")
    asset = asset_graph.upsert(db, program_id, observed, source=source, host_level=True)
    if asset is not None:
        row.asset_id = asset.id


def _link_assets(db, program_id: str, rows, source: str) -> None:
    """Attach each imported row to its asset, creating the node on first sight.

    Failure to classify is not an error — a malformed host in one row of a tool
    export must not fail the whole import. Those rows keep asset_id NULL and can
    be relinked later once the normalizer understands them.
    """
    for row in rows:
        observed = getattr(row, "url", "") or getattr(row, "host", "") or getattr(row, "asset", "")
        asset = asset_graph.upsert(db, program_id, observed, source=source, host_level=True)
        if asset is not None:
            row.asset_id = asset.id


def _dalfox_key(item: ScanItem) -> tuple[str, ...]:
    """A dedup key for a dalfox match that survives a re-run.

    Deliberately excludes the payload and the full URL. dalfox mints a fresh
    marker class per payload (``class=dlx1ec4110f``) and that marker lands in
    both, so keying on either would make every re-scan look like new findings
    and inflate an engagement's count on every run.

    What identifies the same issue across runs is where it is and how it
    injects: the URL without its query values, the injection context and
    parameter (which the parser stores together in ``template_id``), and
    dalfox's own tier — a parameter that moves from reflected to vulnerable is a
    genuinely different fact, so it is stored as its own row rather than
    silently merged into the old one.
    """
    base = ""
    if item.matched_at:
        try:
            parts = urlsplit(item.matched_at)
            base = f"{parts.scheme}://{parts.netloc}{parts.path}"
        except ValueError:
            base = item.matched_at
    return (base, item.template_id or "", item.type or "")


def _dedup_scan_items(
    db: Session,
    incoming: list[ScanItem],
    program_id: str,
    source: str,
) -> tuple[list[ScanItem], list[ScanItem]]:
    """Split incoming scan items into (new, already-stored-equivalent).

    Both halves are returned because the already-stored half still needs its
    provenance recorded: a later job that observes the same issue did observe
    it, and dropping that would misreport which run saw what.
    """
    if not incoming:
        return [], []
    stored = db.query(ScanItem).filter(
        ScanItem.program_id == program_id,
        ScanItem.source == source,
    ).all()
    seen = {_dalfox_key(row): row for row in stored}
    new_items: list[ScanItem] = []
    duplicates: list[ScanItem] = []
    for item in incoming:
        key = _dalfox_key(item)
        existing = seen.get(key)
        if existing is None:
            seen[key] = item
            new_items.append(item)
        else:
            duplicates.append(existing)
    return new_items, duplicates


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
        # Also skip repeats within this upload, not only rows already stored.
        if item.url:
            existing_urls.add(item.url)
        elif item.host:
            existing_hosts.add(item.host)
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
    db: Session, incoming: list[ReconItem], program_id: str, job_id: str | None = None,
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
            _link_one(db, program_id, target, "httpx")
            updated_count += 1
        else:
            item.first_seen_at = now
            db.add(item)
            if host:
                by_host[host] = item  # so later rows in this batch enrich, not duplicate
            new_count += 1
            target = item
        db.flush()
        provenance.link_result(db, job_id, "recon", target.id)

    db.flush()
    for item in incoming:
        _link_one(db, program_id, item, "httpx")

    return new_count, updated_count


@router.post("/engagements/{program_id}/imports")
async def import_results(
    program_id: str,
    background_tasks: BackgroundTasks,
    tool_type: ToolType = Form(...),
    file: UploadFile = File(...),
    job_id: str | None = Form(default=None),
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    provenance.require_job(db, program_id, job_id)

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

    url_parsers = {"ffuf": parse_ffuf, "katana": parse_katana, "gau": parse_gau}
    if tool_type in url_parsers:
        # URL-shaped recon: only rows not already seen for this engagement and
        # source are stored, so re-importing (or chunked uploads) never duplicates.
        recon_items = url_parsers[tool_type](items, program_id)
        new_items, new_count = _dedup_recon(db, recon_items, program_id, tool_type)
        for r in new_items:
            r.job_id = job_id
            db.add(r)
        db.flush()
        _link_assets(db, program_id, new_items, tool_type)
        # Deduplication must retain observations from subsequent executions.
        if job_id:
            urls = {r.url for r in recon_items if r.url}
            for row in db.query(ReconItem).filter(
                ReconItem.program_id == program_id, ReconItem.source == tool_type,
                ReconItem.url.in_(urls),
            ).all():
                provenance.link_result(db, job_id, "recon", row.id)
        imported_count = len(new_items)

    elif tool_type == "httpx":
        recon_items = parse_httpx(items, program_id)
        for r in recon_items:
            r.job_id = job_id  # stamped on genuinely-new rows; enriched rows keep their origin
        new_count, updated_count = _upsert_recon_httpx(db, recon_items, program_id, job_id)
        imported_count = new_count + updated_count

    elif tool_type == "dalfox":
        # Unlike nuclei, dalfox is deduped: a re-scan re-reports every match it
        # still finds, so storing them again would inflate the engagement's
        # count on every run. Duplicates still get their provenance linked —
        # this job did observe them.
        scan_items = parse_dalfox(items, program_id)
        new_items, duplicates = _dedup_scan_items(db, scan_items, program_id, "dalfox")
        for s in new_items:
            s.job_id = job_id
            db.add(s)
        db.flush()
        _link_assets(db, program_id, new_items, "dalfox")
        for row in new_items + duplicates:
            provenance.link_result(db, job_id, "scan", row.id)
        new_count = len(new_items)
        imported_count = new_count

    elif tool_type == "nuclei":
        scan_items = parse_nuclei(items, program_id)
        for s in scan_items:
            s.job_id = job_id
            db.add(s)
        db.flush()
        _link_assets(db, program_id, scan_items, "nuclei")
        for row in scan_items:
            provenance.link_result(db, job_id, "scan", row.id)
        imported_count = len(scan_items)

    # Store "redacted" instead of the real filename — the original file path
    # often leaks local directory structure and isn't useful after import anyway.
    record = ImportRecord(
        program_id=program_id,
        job_id=job_id,
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

    # Webhook: notable scanner matches at/above the user's severity threshold.
    # For dalfox only genuinely-new matches are notified — a re-scan re-reporting
    # a known issue is not news, and alerting on it every run trains the operator
    # to ignore the webhook.
    if tool_type in ("nuclei", "dalfox") and imported_count and user and user.webhook_url:
        threshold = user.notify_min_severity or "high"
        candidates = new_items if tool_type == "dalfox" else scan_items
        notable = [s for s in candidates if severity_meets_threshold(s.severity, threshold)]
        if notable:
            top = max(notable, key=lambda s: ["info", "low", "medium", "high", "critical"].index(s.severity))
            # dalfox reports candidates for a human to verify, so the alert says
            # so rather than calling an unverified match a finding.
            noun = "candidate(s)" if tool_type == "dalfox" else "finding(s)"
            message = (
                f"🚨 VardrMap: {len(notable)} {threshold}+ {noun} imported for "
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
