from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import ScanProfile
from routers.jobs import _VALID_SOURCES, _VALID_TOOLS, _validate_job_config

router = APIRouter(tags=["scan_profiles"])


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    tool_type: str
    target_source: str
    config: Optional[dict] = None


def serialize_profile(p: ScanProfile) -> dict:
    return {
        "id": p.id,
        "program_id": p.program_id,
        "name": p.name,
        "tool_type": p.tool_type,
        "target_source": p.target_source,
        "config": p.config or {},
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/engagements/{program_id}/scan-profiles")
def list_profiles(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    profiles = (
        db.query(ScanProfile)
        .filter(ScanProfile.program_id == program_id)
        .order_by(ScanProfile.created_at.desc())
        .all()
    )
    return {"profiles": [serialize_profile(p) for p in profiles]}


@router.post("/engagements/{program_id}/scan-profiles", status_code=201)
def create_profile(
    program_id: str,
    body: ProfileCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a reusable tool + config preset. Validated identically to a job so a
    profile can never queue a scan the job endpoint would reject."""
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    if body.tool_type not in _VALID_TOOLS:
        raise HTTPException(status_code=400, detail=f"tool_type must be one of {sorted(_VALID_TOOLS)}")
    if body.target_source not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail="target_source must be scope or recon")
    if body.config:
        _validate_job_config(body.tool_type, body.config)

    profile = ScanProfile(
        program_id=program_id,
        owner_github_id=current_user["github_id"],
        name=body.name,
        tool_type=body.tool_type,
        target_source=body.target_source,
        config=body.config or {},
    )
    db.add(profile)
    db.flush()
    log_action(db, current_user["github_id"], "create", "scan_profile", profile.id, program_id)
    db.commit()
    db.refresh(profile)
    return serialize_profile(profile)


@router.delete("/engagements/{program_id}/scan-profiles/{profile_id}")
def delete_profile(
    program_id: str,
    profile_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    profile = (
        db.query(ScanProfile)
        .filter(ScanProfile.id == profile_id, ScanProfile.program_id == program_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    log_action(db, current_user["github_id"], "delete", "scan_profile", profile_id, program_id)
    db.delete(profile)
    db.commit()
    return {"message": "Profile deleted"}
