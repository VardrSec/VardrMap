from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404, log_action
from models import Report
from schemas import ReportCreate, ReportUpdate
from serializers import serialize_report

router = APIRouter()


@router.get("/programs/{program_id}/reports")
def get_reports(
    program_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = get_program_or_404(program_id, current_user, db)
    return {"reports": [serialize_report(r) for r in program.reports]}


@router.post("/programs/{program_id}/reports")
def add_report(
    program_id: str,
    payload: ReportCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    report = Report(
        program_id=program_id,
        finding_id=payload.finding_id or "",
        title=payload.title,
        summary=payload.summary or "",
        steps=payload.steps or "",
        impact=payload.impact or "",
        remediation=payload.remediation or "",
        cwe=payload.cwe or "",
        cvss=payload.cvss or "",
        status=payload.status,
    )
    db.add(report)
    db.flush()
    log_action(db, current_user["github_id"], "create", "report", report.id, program_id)
    db.commit()
    db.refresh(report)
    return serialize_report(report)


@router.patch("/programs/{program_id}/reports/{report_id}")
def update_report(
    program_id: str,
    report_id: str,
    payload: ReportUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    report = db.query(Report).filter(
        Report.id == report_id,
        Report.program_id == program_id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(report, key, value)
    log_action(db, current_user["github_id"], "update", "report", report_id, program_id)
    db.commit()
    db.refresh(report)
    return serialize_report(report)


@router.delete("/programs/{program_id}/reports/{report_id}")
def delete_report(
    program_id: str,
    report_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_program_or_404(program_id, current_user, db)
    report = db.query(Report).filter(
        Report.id == report_id,
        Report.program_id == program_id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    log_action(db, current_user["github_id"], "delete", "report", report_id, program_id)
    db.delete(report)
    db.commit()
    return {"message": "Report deleted"}
