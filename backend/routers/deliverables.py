"""Immutable engagement report revisions assembled from the client's testing record."""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

import finding_history
from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import Authorization, DeliverableRevision, EngagementDeliverable, Evidence, Finding, FindingActivity, ScopeItem
from schemas import ReportStatus
from security import strip_html
from serializers import serialize_finding, serialize_scope_item

router = APIRouter()
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024


class ReportContent(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    executive_summary: str = Field(default="", max_length=20000)
    methodology: str = Field(default="", max_length=20000)
    limitations: str = Field(default="", max_length=20000)
    remediation_priorities: str = Field(default="", max_length=20000)
    # None selects all findings; [] deliberately selects none.
    finding_ids: list[str] | None = Field(default=None, max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("title", "executive_summary", "methodology", "limitations", "remediation_priorities")
    @classmethod
    def clean(cls, value):
        return finding_history.clean_tree(strip_html(value))


class NewRevision(ReportContent):
    base_revision: int = Field(ge=1)


class RevisionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReportStatus


def _iso(value):
    return value.isoformat() if value else None


def _report(db, program_id, report_id, lock=False):
    query = db.query(EngagementDeliverable).filter(EngagementDeliverable.id == report_id, EngagementDeliverable.program_id == program_id)
    report = query.with_for_update().first() if lock else query.first()
    if report is None:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    return report


def _revision(db, report_id, revision):
    row = db.query(DeliverableRevision).filter(DeliverableRevision.deliverable_id == report_id, DeliverableRevision.revision == revision).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    return row


def _serialize(row, content=True):
    result = {"id": row.id, "deliverable_id": row.deliverable_id, "revision": row.revision, "status": row.status, "content_hash": row.content_hash, "actor": row.actor, "created_at": _iso(row.created_at)}
    if content:
        result.update(snapshot=row.snapshot, markdown=row.markdown)
    return result


def _snapshot(db, engagement, body, revision):
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    query = db.query(Finding).filter(Finding.program_id == engagement.id)
    if body.finding_ids is not None:
        query = query.filter(Finding.id.in_(set(body.finding_ids)))
    findings = query.order_by(Finding.created_at, Finding.id).all()
    if body.finding_ids is not None and len(findings) != len(set(body.finding_ids)):
        raise HTTPException(status_code=404, detail="Finding not found")
    ranks = {s: i for i, s in enumerate(("critical", "high", "medium", "low", "info"))}
    findings.sort(key=lambda f: ranks.get(f.severity, 5))
    ids = {f.id for f in findings}
    evidence_ids = set(body.evidence_ids)
    evidence = db.query(Evidence).filter(Evidence.program_id == engagement.id, Evidence.id.in_(evidence_ids)).order_by(Evidence.created_at, Evidence.id).all() if evidence_ids else []
    if len(evidence) != len(evidence_ids):
        raise HTTPException(status_code=404, detail="Evidence not found")
    if any(e.finding_id and e.finding_id not in ids for e in evidence):
        raise HTTPException(status_code=400, detail="Selected evidence belongs to an omitted finding")
    history = db.query(FindingActivity).filter(FindingActivity.program_id == engagement.id, FindingActivity.finding_id.in_(ids), FindingActivity.kind.in_(("remediation", "retest"))).order_by(FindingActivity.created_at, FindingActivity.id).all() if ids else []
    scopes = db.query(ScopeItem).filter(ScopeItem.program_id == engagement.id).order_by(ScopeItem.id).all()
    auths = db.query(Authorization).filter(Authorization.program_id == engagement.id).order_by(Authorization.created_at, Authorization.id).all()
    snapshot = {
        "schema_version": 1, "revision": revision, "generated_at": datetime.now(timezone.utc).isoformat(),
        "editorial": body.model_dump(exclude={"base_revision"}),
        "engagement": {"id": engagement.id, "name": engagement.name, "type": engagement.engagement_type, "status": engagement.engagement_status, "client": engagement.client.name if engagement.client else "", "starts_at": _iso(engagement.starts_at), "ends_at": _iso(engagement.ends_at)},
        "scope": [{**serialize_scope_item(s), "scope_type": s.scope_type} for s in scopes],
        "authorizations": [{"reference": a.reference, "authorized_by": a.authorized_by, "window_start": _iso(a.window_start), "window_end": _iso(a.window_end), "status": a.status} for a in auths],
        "findings": [serialize_finding(f) for f in findings],
        "activity": [{"finding_id": a.finding_id, "kind": a.kind, "outcome": a.outcome, "notes": a.notes, "created_at": _iso(a.created_at)} for a in history],
        "evidence": [{"id": e.id, "finding_id": e.finding_id, "title": e.title, "kind": e.kind, "body": e.body, "content_hash": e.content_hash, "sensitivity": e.sensitivity, "source": e.source} for e in evidence],
    }
    snapshot = finding_history.clean_tree(snapshot)
    if len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(status_code=413, detail="Report exceeds 4 MiB; select fewer findings or evidence items")
    return snapshot


def _markdown(s):
    e, content = s["engagement"], s["editorial"]
    lines = [f"# {content['title']}", f"Revision {s['revision']} | Generated {s['generated_at']}", f"Engagement: {e['name']}", f"Client: {e['client'] or 'Not recorded'}", f"Testing window: {e['starts_at'] or 'Not recorded'} — {e['ends_at'] or 'Not recorded'}", "## Executive summary", content["executive_summary"], "## Scope and authorization"]
    lines += [f"- {r['scope_type'].upper()}: {r['value']} ({r['kind']}) {r['notes']}" for r in s["scope"]]
    lines += [f"- Authorization: {a['reference']} — {a['authorized_by']} ({a['status']}), {a['window_start']} to {a['window_end']}" for a in s["authorizations"]]
    lines += ["## Methodology", content["methodology"], "## Limitations", content["limitations"], "## Remediation priorities", content["remediation_priorities"], "## Findings"]
    for f in s["findings"]:
        lines += [f"### {f['title']}", f"Severity: {f['severity']} | Status: {f['status']} | Asset: {f['asset']}"]
        for key in ("summary", "steps", "impact", "remediation"):
            lines += [f"#### {key.capitalize()}", f[key]]
        for activity in s["activity"]:
            if activity["finding_id"] == f["id"]:
                lines += [f"#### {activity['kind'].capitalize()} — {activity['created_at']}", activity["outcome"] or "", activity["notes"]]
    lines += ["## Selected evidence"]
    for item in s["evidence"]:
        # Indented blocks cannot be escaped by target-controlled triple backticks.
        lines += [f"### {item['title'] or item['id']}", f"Sensitivity: {item['sensitivity']} | Source: {item['source']} | SHA-256: {item['content_hash']}", "\n".join("    " + line for line in item["body"].splitlines())]
    return "\n\n".join(lines) + "\n"


def _save_revision(db, engagement, report, body, actor):
    revision = report.latest_revision + 1
    snapshot = _snapshot(db, engagement, body, revision)
    markdown = _markdown(snapshot)
    row = DeliverableRevision(deliverable_id=report.id, revision=revision, snapshot=snapshot, markdown=markdown, content_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(), actor=actor)
    report.latest_revision = revision
    report.title = body.title
    db.add(row)
    db.flush()
    log_action(db, actor, "create", "deliverable_revision", row.id, engagement.id)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.get("/engagements/{program_id}/deliverables")
def list_deliverables(program_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    get_engagement_or_404(program_id, current_user, db)
    query = db.query(EngagementDeliverable).filter(EngagementDeliverable.program_id == program_id)
    total = query.count()
    rows = query.order_by(EngagementDeliverable.created_at.desc(), EngagementDeliverable.id).offset(offset).limit(limit).all()
    return {"deliverables": [{"id": r.id, "title": r.title, "latest_revision": r.latest_revision, "created_at": _iso(r.created_at)} for r in rows], "total": total}


@router.post("/engagements/{program_id}/deliverables", status_code=201)
def create_deliverable(program_id: str, body: ReportContent, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    report = EngagementDeliverable(program_id=program_id, title=body.title, latest_revision=0)
    db.add(report)
    db.flush()
    return _save_revision(db, engagement, report, body, current_user["github_id"])


@router.post("/engagements/{program_id}/deliverables/{report_id}/revisions", status_code=201)
def create_revision(program_id: str, report_id: str, body: NewRevision, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    report = _report(db, program_id, report_id, lock=True)
    if body.base_revision != report.latest_revision:
        raise HTTPException(status_code=409, detail="A newer revision exists; reload it before saving")
    return _save_revision(db, engagement, report, body, current_user["github_id"])


@router.get("/engagements/{program_id}/deliverables/{report_id}/revisions")
def list_revisions(program_id: str, report_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    get_engagement_or_404(program_id, current_user, db)
    _report(db, program_id, report_id)
    query = db.query(DeliverableRevision).filter(DeliverableRevision.deliverable_id == report_id)
    return {"revisions": [_serialize(r, False) for r in query.order_by(DeliverableRevision.revision.desc()).offset(offset).limit(limit).all()], "total": query.count()}


@router.get("/engagements/{program_id}/deliverables/{report_id}/revisions/{revision}")
def get_revision(program_id: str, report_id: str, revision: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    get_engagement_or_404(program_id, current_user, db)
    _report(db, program_id, report_id)
    return _serialize(_revision(db, report_id, revision))


@router.get("/engagements/{program_id}/deliverables/{report_id}/revisions/{revision}/markdown", response_class=PlainTextResponse)
def export_revision(program_id: str, report_id: str, revision: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    get_engagement_or_404(program_id, current_user, db)
    report = _report(db, program_id, report_id)
    row = _revision(db, report_id, revision)
    return PlainTextResponse(row.markdown, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="engagement-report-{report.id}-v{revision}.md"'})


@router.patch("/engagements/{program_id}/deliverables/{report_id}/revisions/{revision}")
def update_revision_status(program_id: str, report_id: str, revision: int, body: RevisionStatus, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    _report(db, program_id, report_id)
    row = _revision(db, report_id, revision)
    row.status = body.status
    log_action(db, current_user["github_id"], "update_status", "deliverable_revision", row.id, program_id)
    db.commit()
    return _serialize(row)
