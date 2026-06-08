from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from models import Finding
from schemas import FindingCreate, FindingUpdate
from serializers import serialize_finding

router = APIRouter()


@router.get("/programs/{program_id}/findings")
def get_findings(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    return {"findings": [serialize_finding(f) for f in program.findings]}


@router.post("/programs/{program_id}/findings")
def add_finding(
    program_id: str,
    payload: FindingCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    finding = Finding(
        program_id=program_id,
        title=payload.title,
        severity=payload.severity,
        asset=payload.asset or "",
        status=payload.status,
        summary=payload.summary or "",
        steps=payload.steps or "",
        impact=payload.impact or "",
        remediation=payload.remediation or "",
    )
    db.add(finding)
    db.flush()
    log_action(db, current_user["github_id"], "create", "finding", finding.id, program_id)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding)


@router.patch("/programs/{program_id}/findings/{finding_id}")
def update_finding(
    program_id: str,
    finding_id: str,
    payload: FindingUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.program_id == program_id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(finding, key, value)
    log_action(db, current_user["github_id"], "update", "finding", finding_id, program_id)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding)


@router.delete("/programs/{program_id}/findings/{finding_id}")
def delete_finding(
    program_id: str,
    finding_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.program_id == program_id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    log_action(db, current_user["github_id"], "delete", "finding", finding_id, program_id)
    db.delete(finding)
    db.commit()
    return {"message": "Finding deleted"}
