"""
User settings — notification webhook URL and severity threshold.

The webhook URL is stored in plaintext (it must be usable, unlike API keys
which are hashed) and is only ever returned to its owner.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, log_action
from models import User
from notifications import VALID_SEVERITIES, validate_webhook_url

router = APIRouter(tags=["settings"])

_DEFAULTS = {"webhook_url": "", "notify_min_severity": "high"}


class SettingsUpdate(BaseModel):
    webhook_url: str | None = Field(default=None, max_length=500)  # "" clears the webhook
    notify_min_severity: str | None = None  # info|low|medium|high|critical

    @field_validator("webhook_url", mode="before")
    @classmethod
    def trim_url(cls, v): return v.strip() if isinstance(v, str) else v


def _serialize(user: User) -> dict:
    return {
        "webhook_url": user.webhook_url or "",
        "notify_min_severity": user.notify_min_severity or "high",
    }


@router.get("/settings")
def get_settings(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if not user:
        return dict(_DEFAULTS)
    return _serialize(user)


@router.patch("/settings")
def update_settings(
    body: SettingsUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.webhook_url:
        error = validate_webhook_url(body.webhook_url)
        if error:
            raise HTTPException(status_code=400, detail=error)
    if body.notify_min_severity is not None and body.notify_min_severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"notify_min_severity must be one of {sorted(VALID_SEVERITIES)}",
        )

    # Settings can be saved before /auth/sync ever ran — upsert the user row
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if not user:
        user = User(
            github_id=current_user["github_id"],
            username=current_user.get("username", ""),
            email=current_user.get("email", ""),
        )
        db.add(user)

    if body.webhook_url is not None:
        user.webhook_url = body.webhook_url
    if body.notify_min_severity is not None:
        user.notify_min_severity = body.notify_min_severity

    log_action(db, current_user["github_id"], "update", "settings", current_user["github_id"])
    db.commit()
    db.refresh(user)
    return _serialize(user)
