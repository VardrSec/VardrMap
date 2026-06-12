import os
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from models import ImportRecord, Program, User
from notifications import send_webhook, severity_meets_threshold
from parsers import normalize_to_list, parse_ffuf, parse_httpx, parse_json_or_jsonl, parse_nuclei
from schemas import ToolType
from serializers import serialize_import_record, serialize_program

router = APIRouter()

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "2097152"))

ALLOWED_EXTENSIONS = {".json", ".jsonl"}
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/x-ndjson",
    "application/octet-stream",
    "text/plain",
}


@router.post("/programs/{program_id}/imports")
async def import_results(
    program_id: str,
    background_tasks: BackgroundTasks,
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
    db.flush()
    log_action(db, current_user["github_id"], "create", "import", record.id, program_id)
    db.commit()

    program = db.query(Program).filter(Program.id == program_id).first()

    # Webhook notification for notable nuclei findings (at/above the user's threshold)
    if tool_type == "nuclei" and imported_count:
        user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
        if user and user.webhook_url:
            threshold = user.notify_min_severity or "high"
            notable = [s for s in scan_items if severity_meets_threshold(s.severity, threshold)]
            if notable:
                top = max(notable, key=lambda s: ["info", "low", "medium", "high", "critical"].index(s.severity))
                message = (
                    f"🚨 VardrMap: {len(notable)} {threshold}+ finding(s) imported for "
                    f"{program.name if program else program_id} — top: [{top.severity}] {top.title or top.template_id}"
                )
                background_tasks.add_task(send_webhook, user.webhook_url, message)
    return {
        "message": "Import complete",
        "import_record": serialize_import_record(record),
        "program": serialize_program(program, db),
    }
