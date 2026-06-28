from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action, require_member_write
from models import ScopeItem
from schemas import ScopeItemCreate
from serializers import serialize_scope_item

router = APIRouter()


@router.post("/programs/{program_id}/scope/in")
def add_in_scope_item(
    program_id: str,
    payload: ScopeItemCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    require_member_write(program, current_user, db)
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


@router.post("/programs/{program_id}/scope/out")
def add_out_scope_item(
    program_id: str,
    payload: ScopeItemCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    require_member_write(program, current_user, db)
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


@router.delete("/programs/{program_id}/scope/{scope_type}/{item_id}")
def delete_scope_item(
    program_id: str,
    scope_type: str,
    item_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if scope_type not in ["in", "out"]:
        raise HTTPException(status_code=400, detail="Invalid scope type")
    program = get_program_or_404(program_id, current_user, db)
    require_member_write(program, current_user, db)
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
