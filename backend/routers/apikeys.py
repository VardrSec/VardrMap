import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user
from models import ApiKey, User
from schemas import ApiKeyCreate

router = APIRouter()

_PREFIX = "vmap_"
_MAX_KEYS_PER_USER = 10


@router.post("/auth/apikeys")
def create_api_key(
    payload: ApiKeyCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ensure user row exists before inserting the API key (FK safety, same
    # pattern as create_program — JWT auth gives us the user's info directly).
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if not user:
        user = User(
            github_id=current_user["github_id"],
            username=current_user["username"],
            email=current_user["email"],
        )
        db.add(user)
        db.flush()

    existing = db.query(ApiKey).filter(ApiKey.github_id == current_user["github_id"]).count()
    if existing >= _MAX_KEYS_PER_USER:
        raise HTTPException(status_code=400, detail=f"Maximum {_MAX_KEYS_PER_USER} API keys allowed")

    raw = _PREFIX + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()

    key = ApiKey(
        github_id=current_user["github_id"],
        key_hash=key_hash,
        label=payload.label or "",
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    return {
        "id": key.id,
        "label": key.label,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "token": raw,  # plaintext shown once — not stored, only the hash is
    }


@router.get("/auth/apikeys")
def list_api_keys(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.github_id == current_user["github_id"])
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return {
        "keys": [
            {
                "id": k.id,
                "label": k.label,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ]
    }


@router.delete("/auth/apikeys/{key_id}")
def revoke_api_key(
    key_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.github_id == current_user["github_id"],
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(key)
    db.commit()
    return {"message": "API key revoked"}
