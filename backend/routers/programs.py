from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action, require_program_owner
from models import Finding, ManualTest, Program, ProgramMember, ReconItem, Report, ScanItem, Submission, User
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



@router.get("/programs")
def get_programs(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    github_id = current_user["github_id"]
    owned = db.query(Program).filter(Program.owner_github_id == github_id).all()

    # Also include programs where this user is an invited member
    member_program_ids = [
        row[0]
        for row in db.query(ProgramMember.program_id).filter(
            ProgramMember.member_github_id == github_id
        ).all()
    ]
    shared = (
        db.query(Program)
        .filter(Program.id.in_(member_program_ids))
        .all()
        if member_program_ids else []
    )

    seen = {p.id for p in owned}
    all_programs = owned + [p for p in shared if p.id not in seen]
    return {"programs": [serialize_program(p, db, github_id=github_id) for p in all_programs]}


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
    return serialize_program(program, db, github_id=current_user["github_id"])


@router.get("/programs/{program_id}")
def get_program(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    return serialize_program(program, db, github_id=current_user["github_id"])


@router.patch("/programs/{program_id}")
def update_program(
    program_id: str,
    payload: ProgramUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    require_program_owner(program, current_user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(program, key, value)
    log_action(db, current_user["github_id"], "update", "program", program_id, program_id)
    db.commit()
    db.refresh(program)
    return serialize_program(program, db, github_id=current_user["github_id"])


@router.get("/programs/{program_id}/stats")
def get_program_stats(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lightweight aggregate stats for a program — used by the Dashboard stat cards.
    Returns counts and breakdowns without serializing full objects."""
    get_program_or_404(program_id, current_user, db)

    def count(model, extra_filter=None):
        q = db.query(func.count(model.id)).filter(model.program_id == program_id)  # type: ignore[attr-defined]
        if extra_filter is not None:
            q = q.filter(extra_filter)
        return q.scalar() or 0

    sev_rows = (
        db.query(Finding.severity, func.count(Finding.id))
        .filter(Finding.program_id == program_id)
        .group_by(Finding.severity)
        .all()
    )

    sub_status_rows = (
        db.query(Submission.status, func.count(Submission.id))
        .filter(Submission.program_id == program_id)
        .group_by(Submission.status)
        .all()
    )

    return {
        "recon_count":          count(ReconItem),
        "scans_count":          count(ScanItem),
        "findings_count":       count(Finding),
        "manual_tests_count":   count(ManualTest),
        "reports_count":        count(Report),
        "submissions_count":    count(Submission),
        "findings_by_severity": {sev: cnt for sev, cnt in sev_rows},
        "submissions_by_status": {status: cnt for status, cnt in sub_status_rows},
    }


@router.delete("/programs/{program_id}")
def delete_program(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    require_program_owner(program, current_user)
    log_action(db, current_user["github_id"], "delete", "program", program_id)
    db.delete(program)
    db.commit()
    return {"message": "Program deleted"}
