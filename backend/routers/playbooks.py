from db import get_db
from deps import get_current_user, get_engagement_or_404
from fastapi import APIRouter, Depends, HTTPException
from playbooks import CATALOG
from sqlalchemy.orm import Session

router = APIRouter(tags=["playbooks"])


@router.get("/engagements/{program_id}/playbooks")
def list_playbooks(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    return {
        "playbooks": [
            {"id": p.id, "title": p.title, "version": p.version, "use_when": p.use_when}
            for p in CATALOG.values()
        ],
        "total": len(CATALOG),
    }


@router.get("/engagements/{program_id}/playbooks/{playbook_id}")
def get_playbook(
    program_id: str,
    playbook_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    if playbook_id not in CATALOG:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return CATALOG[playbook_id].model_dump()
