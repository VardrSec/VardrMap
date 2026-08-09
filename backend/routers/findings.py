import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import Finding
from schemas import FindingCreate, FindingUpdate
from serializers import serialize_finding

router = APIRouter()


@router.get("/engagements/{program_id}/findings")
def get_findings(
    program_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str = Query(default=""),
    severity: str = Query(default=""),
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    query = db.query(Finding).filter(Finding.program_id == program_id)
    if search:
        like = f"%{search}%"
        query = query.filter(Finding.title.ilike(like) | Finding.asset.ilike(like))
    if severity:
        query = query.filter(Finding.severity == severity)
    total = query.count()
    findings = query.order_by(Finding.created_at.desc()).offset(offset).limit(limit).all()
    return {"findings": [serialize_finding(f) for f in findings], "total": total, "offset": offset, "limit": limit}


@router.post("/engagements/{program_id}/findings")
def add_finding(
    program_id: str,
    payload: FindingCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
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


@router.patch("/engagements/{program_id}/findings/{finding_id}")
def update_finding(
    program_id: str,
    finding_id: str,
    payload: FindingUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
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


_SUGGEST_PROMPT = """\
You are a penetration testing assistant. Given the following finding, provide concise, \
actionable suggestions for CVSS score, impact statement, and remediation.

Finding title: {title}
Severity: {severity}
Asset: {asset}
Summary: {summary}
Steps to reproduce: {steps}

Respond with valid JSON only — no markdown fences, no explanation:
{{"cvss": "<score and label e.g. 7.5 (High)>", "impact": "<2-3 sentence impact>", "remediation": "<2-3 sentence remediation>"}}"""


@router.post("/engagements/{program_id}/findings/{finding_id}/suggest")
def suggest_finding(
    program_id: str,
    finding_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Call Claude API to draft CVSS, impact, and remediation for a finding."""
    # BOLA scope check first — wrong-user gets 404, not a 503 that leaks API state
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)  # AI actions cost money — viewers can't trigger them
    finding = db.query(Finding).filter(
        Finding.id == finding_id,
        Finding.program_id == program_id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI suggestions require ANTHROPIC_API_KEY to be configured on the server",
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": _SUGGEST_PROMPT.format(
                    title=finding.title,
                    severity=finding.severity,
                    asset=finding.asset or "(not specified)",
                    summary=finding.summary or "(not specified)",
                    steps=finding.steps or "(not specified)",
                ),
            }],
        )
        raw = message.content[0].text.strip()
        suggestion = json.loads(raw)
        return {
            "cvss":        str(suggestion.get("cvss", "")),
            "impact":      str(suggestion.get("impact", "")),
            "remediation": str(suggestion.get("remediation", "")),
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI returned non-JSON response; try again")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI request failed: {exc}")


@router.delete("/engagements/{program_id}/findings/{finding_id}")
def delete_finding(
    program_id: str,
    finding_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
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
