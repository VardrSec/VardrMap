from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404
from models import ReconItem
from serializers import serialize_recon_item

router = APIRouter()


@router.get("/programs/{program_id}/recon")
def get_recon(
    program_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = None,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    query = db.query(ReconItem).filter(ReconItem.program_id == program_id)
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            ReconItem.url.ilike(term),
            ReconItem.host.ilike(term),
            ReconItem.path.ilike(term),
            ReconItem.title.ilike(term),
        ))
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return {"recon": [serialize_recon_item(r) for r in items], "total": total, "offset": offset, "limit": limit}
