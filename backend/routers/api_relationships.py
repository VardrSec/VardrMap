"""Boundary hypotheses derived from reviewed identity, tenant and resource context."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from authorization_relationships import build_relationships
from db import get_db
from deps import get_current_user, get_engagement_or_404

router = APIRouter(tags=["api-surface"])


@router.get("/engagements/{program_id}/api/relationships")
def authorization_relationships(
    program_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read-only. Questions worth testing, from facts a person reviewed; never findings."""
    get_engagement_or_404(program_id, current_user, db)
    data = build_relationships(db, program_id)
    data["filtered_total"] = len(data["hypotheses"])
    data["hypotheses"] = data["hypotheses"][offset : offset + limit]
    return data
