"""Authorization-testing coverage for an engagement's observed API operations."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from authorization_coverage import STATES, build_coverage
from db import get_db
from deps import get_current_user, get_engagement_or_404

router = APIRouter(tags=["api-surface"])


@router.get("/engagements/{program_id}/api/coverage")
def authorization_coverage(
    program_id: str,
    state: str = Query(default="", max_length=30),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read-only. Computed on demand from stored inventory, cases, jobs and evidence."""
    get_engagement_or_404(program_id, current_user, db)
    data = build_coverage(db, program_id)
    operations = data["operations"]
    if state in STATES:
        operations = [op for op in operations if op["state"] == state]
    data["filtered_total"] = len(operations)
    data["operations"] = operations[offset : offset + limit]
    return data
