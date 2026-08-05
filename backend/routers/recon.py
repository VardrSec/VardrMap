from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404
from models import ReconItem
from serializers import serialize_recon_item

router = APIRouter()


@router.get("/engagements/{program_id}/recon")
def get_recon(
    program_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = None,
    status_code: Optional[int] = None,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    query = db.query(ReconItem).filter(ReconItem.program_id == program_id)
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            ReconItem.url.ilike(term),
            ReconItem.host.ilike(term),
            ReconItem.path.ilike(term),
            ReconItem.title.ilike(term),
        ))
    if status_code is not None:
        query = query.filter(ReconItem.status_code == status_code)
    total = query.count()
    # Surface enriched/live rows first: a probed host (has a status_code) outranks a
    # bare discovered host, so the Review page doesn't lead with blank rows.
    items = (
        query.order_by(ReconItem.status_code.is_(None), ReconItem.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"recon": [serialize_recon_item(r) for r in items], "total": total, "offset": offset, "limit": limit}
