import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import ScopeItem
from schemas import ScopeImportRequest, ScopeItemCreate
from security import sanitize_identifier
from serializers import serialize_scope_item

router = APIRouter()

# A program's scope export lists assets by type. Map each HackerOne asset_type to
# one of our scope kinds; URL and anything unrecognized are decided from the value
# shape instead (see _kind_for), and the original asset_type is always kept in the
# note so nothing is silently reclassified.
_H1_KIND = {
    "WILDCARD": "domain",
    "API": "api",
    "CIDR": "cidr",
    "IP_ADDRESS": "cidr",
    "GOOGLE_PLAY_APP_ID": "mobile",
    "APPLE_STORE_APP_ID": "mobile",
    "WINDOWS_APP_STORE_APP_ID": "mobile",
    "TESTFLIGHT": "mobile",
    "OTHER_APK": "mobile",
    "OTHER_IPA": "mobile",
}
_SEVERITIES = {"info", "low", "medium", "high", "critical"}
_MAX_IMPORT_ROWS = 5000


def _kind_for(asset_type: str, value: str) -> str:
    mapped = _H1_KIND.get(asset_type)
    if mapped:
        return mapped
    v = value.strip().lower()
    if v.startswith(("http://", "https://")) or "/" in v:
        return "url"
    return "domain"


def _parse_hackerone_scope(text: str) -> tuple[list[dict], list[dict]]:
    """Parse a HackerOne scope CSV into (items, skipped).

    Each item is ``{value, kind, scope_type, max_severity, notes}``; a skipped row
    is ``{line, identifier, reason}``. Pure and side-effect-free so it can be
    tested and previewed without touching the database.
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "identifier" not in reader.fieldnames:
        raise HTTPException(
            status_code=400,
            detail="CSV must have a header row with an 'identifier' column (HackerOne scope export).",
        )
    items: list[dict] = []
    skipped: list[dict] = []
    for i, row in enumerate(reader, start=2):  # line 1 is the header
        if len(items) + len(skipped) >= _MAX_IMPORT_ROWS:
            raise HTTPException(status_code=400, detail=f"too many rows; the limit is {_MAX_IMPORT_ROWS}")
        identifier = (row.get("identifier") or "").strip()
        if not identifier:
            continue
        if len(identifier) > 500:
            skipped.append({"line": i, "identifier": identifier[:120], "reason": "identifier too long"})
            continue
        try:
            value = sanitize_identifier(identifier)
        except ValueError:
            skipped.append({"line": i, "identifier": identifier[:120], "reason": "invalid characters"})
            continue
        if not value:
            skipped.append({"line": i, "identifier": identifier[:120], "reason": "empty after sanitizing"})
            continue
        asset_type = (row.get("asset_type") or "").strip().upper()
        eligible = (row.get("eligible_for_submission") or "true").strip().lower()
        scope_type = "out" if eligible == "false" else "in"
        severity = (row.get("max_severity") or "").strip().lower()
        if severity not in _SEVERITIES:
            severity = ""
        instruction = (row.get("instruction") or "").strip()
        note = f"HackerOne {asset_type or 'asset'}"
        if instruction:
            note = f"{note} — {instruction}"
        items.append({
            "value": value,
            "kind": _kind_for(asset_type, value),
            "scope_type": scope_type,
            "max_severity": severity,
            "notes": note[:2000],
        })
    return items, skipped


@router.post("/engagements/{program_id}/scope/in")
def add_in_scope_item(
    program_id: str,
    payload: ScopeItemCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    item = ScopeItem(
        program_id=program_id,
        scope_type="in",
        value=payload.value,
        kind=payload.kind,
        notes=payload.notes or "",
    )
    db.add(item)
    db.flush()
    log_action(db, current_user["github_id"], "create", "scope_item", item.id, program_id)
    db.commit()
    db.refresh(item)
    return serialize_scope_item(item)


@router.post("/engagements/{program_id}/scope/out")
def add_out_scope_item(
    program_id: str,
    payload: ScopeItemCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    item = ScopeItem(
        program_id=program_id,
        scope_type="out",
        value=payload.value,
        kind=payload.kind,
        notes=payload.notes or "",
    )
    db.add(item)
    db.flush()
    log_action(db, current_user["github_id"], "create", "scope_item", item.id, program_id)
    db.commit()
    db.refresh(item)
    return serialize_scope_item(item)


@router.delete("/engagements/{program_id}/scope/{scope_type}/{item_id}")
def delete_scope_item(
    program_id: str,
    scope_type: str,
    item_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if scope_type not in ["in", "out"]:
        raise HTTPException(status_code=400, detail="Invalid scope type")
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    item = db.query(ScopeItem).filter(
        ScopeItem.id == item_id,
        ScopeItem.program_id == program_id,
        ScopeItem.scope_type == scope_type,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scope item not found")
    log_action(db, current_user["github_id"], "delete", "scope_item", item_id, program_id)
    db.delete(item)
    db.commit()
    return {"message": "Scope item deleted"}


@router.post("/engagements/{program_id}/scope/import")
def import_scope(
    program_id: str,
    payload: ScopeImportRequest,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import many scope items from a program's scope CSV.

    ``commit`` false returns a preview — every parsed row with what it maps to,
    rows that are already in scope, and rows that could not be parsed — and writes
    nothing. ``commit`` true inserts only the rows that are new. Nothing is ever
    deleted, so re-importing an updated export only adds what changed.
    """
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)

    parsed, skipped = _parse_hackerone_scope(payload.csv)

    existing = {
        (s.scope_type, s.value)
        for s in db.query(ScopeItem.scope_type, ScopeItem.value).filter(
            ScopeItem.program_id == program_id
        )
    }
    seen: set[tuple[str, str]] = set()
    new_items: list[dict] = []
    duplicates: list[dict] = []
    for item in parsed:
        key = (item["scope_type"], item["value"])
        if key in existing or key in seen:
            duplicates.append(item)
            continue
        seen.add(key)
        new_items.append(item)

    created = 0
    if payload.commit and new_items:
        for item in new_items:
            db.add(ScopeItem(
                program_id=program_id,
                scope_type=item["scope_type"],
                value=item["value"],
                kind=item["kind"],
                notes=item["notes"],
                max_severity=item["max_severity"],
            ))
        log_action(
            db, current_user["github_id"], "import", "scope_item", program_id, program_id
        )
        db.commit()
        created = len(new_items)

    return {
        "format": payload.format,
        "committed": payload.commit,
        "created": created,
        "summary": {
            "in": sum(1 for i in new_items if i["scope_type"] == "in"),
            "out": sum(1 for i in new_items if i["scope_type"] == "out"),
            "duplicates": len(duplicates),
            "skipped": len(skipped),
            "total_rows": len(parsed) + len(skipped),
        },
        "new_items": new_items,
        "duplicates": duplicates,
        "skipped": skipped,
    }
