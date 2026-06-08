from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from models import ScanItem
from schemas import BulkScanStatusUpdate, ScanStatusUpdate
from serializers import serialize_scan_item

router = APIRouter()


@router.get("/programs/{program_id}/scans")
def get_scans(
    program_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = None,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    query = db.query(ScanItem).filter(ScanItem.program_id == program_id)
    if status:
        query = query.filter(ScanItem.status == status)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return {"scans": [serialize_scan_item(s) for s in items], "total": total, "offset": offset, "limit": limit}


@router.post("/programs/{program_id}/scans/bulk-status")
def bulk_update_scan_status(
    program_id: str,
    payload: BulkScanStatusUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    scans = db.query(ScanItem).filter(
        ScanItem.program_id == program_id,
        ScanItem.id.in_(payload.ids),
    ).all()
    for scan in scans:
        scan.status = payload.status
    log_action(db, current_user["github_id"], "update", "scan_item", f"bulk:{len(scans)}", program_id)
    db.commit()
    return {"updated": len(scans)}


@router.patch("/programs/{program_id}/scans/{scan_id}")
def update_scan_status(
    program_id: str,
    scan_id: str,
    payload: ScanStatusUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
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
