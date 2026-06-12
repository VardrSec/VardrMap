"""Program membership — invite collaborators to read and write a program."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action, require_program_owner
from models import ProgramMember

router = APIRouter(tags=["members"])

_MAX_MEMBERS = 20


class MemberAdd(BaseModel):
    github_id: str = Field(min_length=1, max_length=100)
    role: str = "member"  # "member" is the only role in v0.19.0


def serialize(m: ProgramMember) -> dict:
    return {
        "id":               m.id,
        "program_id":       m.program_id,
        "member_github_id": m.member_github_id,
        "role":             m.role,
        "invited_at":       m.invited_at.isoformat() if m.invited_at else None,
    }


@router.get("/programs/{program_id}/members")
def list_members(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    rows = db.query(ProgramMember).filter(ProgramMember.program_id == program_id).all()
    return {
        "owner_github_id": program.owner_github_id,
        "members": [serialize(m) for m in rows],
    }


@router.post("/programs/{program_id}/members", status_code=201)
def add_member(
    program_id: str,
    body: MemberAdd,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    require_program_owner(program, current_user)

    if body.github_id == current_user["github_id"]:
        raise HTTPException(status_code=400, detail="Cannot add the program owner as a member")

    existing = db.query(ProgramMember).filter(
        ProgramMember.program_id == program_id,
        ProgramMember.member_github_id == body.github_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")

    count = db.query(ProgramMember).filter(ProgramMember.program_id == program_id).count()
    if count >= _MAX_MEMBERS:
        raise HTTPException(status_code=400, detail=f"Maximum {_MAX_MEMBERS} members per program")

    member = ProgramMember(
        program_id=program_id,
        owner_github_id=current_user["github_id"],
        member_github_id=body.github_id,
        role="member",
    )
    db.add(member)
    db.flush()
    log_action(db, current_user["github_id"], "create", "program_member", member.id, program_id)
    db.commit()
    db.refresh(member)
    return serialize(member)


@router.delete("/programs/{program_id}/members/{member_github_id}", status_code=200)
def remove_member(
    program_id: str,
    member_github_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    require_program_owner(program, current_user)

    member = db.query(ProgramMember).filter(
        ProgramMember.program_id == program_id,
        ProgramMember.member_github_id == member_github_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    log_action(db, current_user["github_id"], "delete", "program_member", member.id, program_id)
    db.delete(member)
    db.commit()
    return {"message": "Member removed"}
