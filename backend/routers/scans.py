import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import ScanItem
from schemas import BulkScanStatusUpdate, ScanStatusUpdate
from serializers import serialize_scan_item

router = APIRouter()

# Cap how many items go to the model in one call — keeps token cost and latency bounded.
_TRIAGE_BATCH_MAX = 25

_TRIAGE_PROMPT = """\
You are a bug bounty triage assistant. Below is a JSON array of raw nuclei scan results \
for a single engagement. For each result, judge how much a hunter should prioritize it and \
whether it is likely a false positive or low-value noise.

Scan results:
{items}

Respond with valid JSON only — no markdown fences, no prose. Return a JSON array where \
each element is:
{{"id": "<the id from the input>", "priority": "high|medium|low|noise", \
"false_positive": true|false, "rationale": "<one sentence, max 20 words>"}}
Return exactly one element per input id, preserving ids verbatim."""


@router.get("/engagements/{program_id}/scans")
def get_scans(
    program_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = None,
    job_id: Optional[str] = None,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    query = db.query(ScanItem).filter(ScanItem.program_id == program_id)
    if status:
        query = query.filter(ScanItem.status == status)
    if job_id:
        query = query.filter(ScanItem.job_id == job_id)
    total = query.count()
    items = query.order_by(ScanItem.id).offset(offset).limit(limit).all()
    return {"scans": [serialize_scan_item(s) for s in items], "total": total, "offset": offset, "limit": limit}


@router.post("/engagements/{program_id}/scans/bulk-status")
def bulk_update_scan_status(
    program_id: str,
    payload: BulkScanStatusUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    scans = db.query(ScanItem).filter(
        ScanItem.program_id == program_id,
        ScanItem.id.in_(payload.ids),
    ).all()
    for scan in scans:
        scan.status = payload.status
    log_action(db, current_user["github_id"], "update", "scan_item", f"bulk:{len(scans)}", program_id)
    db.commit()
    return {"updated": len(scans)}


class ScanTriageRequest(BaseModel):
    # Specific scan-item ids to triage. Empty => triage the newest "new" items.
    ids: list[str] = Field(default_factory=list)


@router.post("/engagements/{program_id}/scans/triage")
def triage_scans(
    program_id: str,
    payload: ScanTriageRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a batch of raw nuclei scan items to Claude and get back a prioritized,
    false-positive-flagged triage list. Turns the scan firehose into a ranked queue.

    Unlike the per-finding suggest endpoint, this operates on un-promoted ScanItems —
    it is the first pass over raw tool output, before anything becomes a Finding.
    """
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)  # AI actions cost money — viewers can't trigger them

    query = db.query(ScanItem).filter(ScanItem.program_id == program_id)
    if payload.ids:
        query = query.filter(ScanItem.id.in_(payload.ids))
    else:
        query = query.filter(ScanItem.status == "new")
    items = query.order_by(ScanItem.id).limit(_TRIAGE_BATCH_MAX).all()
    if not items:
        return {"triage": []}

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI triage requires ANTHROPIC_API_KEY to be configured on the server",
        )

    compact = [
        {
            "id": s.id,
            "template_id": s.template_id or "",
            "title": s.title or "",
            "severity": s.severity or "info",
            "asset": s.asset or s.matched_at or "",
            "description": (s.description or "")[:300],
        }
        for s in items
    ]

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": _TRIAGE_PROMPT.format(items=json.dumps(compact, indent=2)),
            }],
        )
        raw = message.content[0].text.strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("expected a JSON array")
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI returned non-JSON response; try again")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI request failed: {exc}")

    # Only echo back triage rows whose id is one we actually sent — the model can't
    # smuggle in ids for other users' items, and malformed rows are dropped.
    valid_ids = {s.id for s in items}
    triage = [
        {
            "id": row.get("id"),
            "priority": str(row.get("priority", "")),
            "false_positive": bool(row.get("false_positive", False)),
            "rationale": str(row.get("rationale", ""))[:200],
        }
        for row in parsed
        if isinstance(row, dict) and row.get("id") in valid_ids
    ]
    return {"triage": triage}


@router.patch("/engagements/{program_id}/scans/{scan_id}")
def update_scan_status(
    program_id: str,
    scan_id: str,
    payload: ScanStatusUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    scan = db.query(ScanItem).filter(
        ScanItem.id == scan_id,
        ScanItem.program_id == program_id,
    ).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan item not found")
    scan.status = payload.status
    log_action(db, current_user["github_id"], "update", "scan_item", scan_id, program_id)
    db.commit()
    db.refresh(scan)
    return serialize_scan_item(scan)
