from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from models import Program, User
from schemas import ProgramCreate, ProgramUpdate
from serializers import serialize_program

router = APIRouter()


@router.post("/auth/sync")
def auth_sync(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if user:
        user.username = current_user["username"]
        user.email = current_user["email"]
    else:
        user = User(
            github_id=current_user["github_id"],
            username=current_user["username"],
            email=current_user["email"],
        )
        db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "github_id": user.github_id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/me")
def me(current_user: dict[str, str] = Depends(get_current_user)):
    return current_user


@router.get("/programs")
def get_programs(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(Program).filter(Program.owner_github_id == current_user["github_id"]).all()
    return {"programs": [serialize_program(p, db) for p in rows]}


@router.post("/programs")
def create_program(
    payload: ProgramCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ensure user row exists before creating program (FK safety)
    user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
    if not user:
        user = User(
            github_id=current_user["github_id"],
            username=current_user["username"],
            email=current_user["email"],
        )
        db.add(user)
        db.flush()

    program = Program(
        owner_github_id=current_user["github_id"],
        name=payload.name,
        platform=payload.platform or "",
        program_url=payload.program_url or "",
        scope_summary=payload.scope_summary or "",
        severity_guidance=payload.severity_guidance or "",
        safe_harbor_notes=payload.safe_harbor_notes or "",
    )
    db.add(program)
    db.flush()
    log_action(db, current_user["github_id"], "create", "program", program.id)
    db.commit()
    db.refresh(program)
    return serialize_program(program, db)


@router.get("/programs/{program_id}")
def get_program(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    return serialize_program(program, db)


@router.patch("/programs/{program_id}")
def update_program(
    program_id: str,
    payload: ProgramUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(program, key, value)
    log_action(db, current_user["github_id"], "update", "program", program_id, program_id)
    db.commit()
    db.refresh(program)
    return serialize_program(program, db)


@router.delete("/programs/{program_id}")
def delete_program(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    log_action(db, current_user["github_id"], "delete", "program", program_id)
    db.delete(program)
    db.commit()
    return {"message": "Program deleted"}
