from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Authorization, Client, Finding, ImportRecord, ManualTest, Engagement, EngagementMember, ReconItem, Report, ScanItem, ScopeItem, Service


def serialize_scope_item(item: ScopeItem) -> dict:
    return {
        "id": item.id,
        "value": item.value,
        "kind": item.kind,
        "notes": item.notes or "",
    }


def serialize_manual_test(t: ManualTest) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "hypothesis": t.hypothesis or "",
        "payload": t.payload or "",
        "evidence": t.evidence or "",
        "status": t.status,
    }


def serialize_finding(f: Finding) -> dict:
    return {
        "id": f.id,
        "title": f.title,
        "severity": f.severity,
        "asset": f.asset or "",
        "status": f.status,
        "summary": f.summary or "",
        "steps": f.steps or "",
        "impact": f.impact or "",
        "remediation": f.remediation or "",
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def serialize_report(r: Report) -> dict:
    return {
        "id": r.id,
        "finding_id": r.finding_id or "",
        "title": r.title,
        "summary": r.summary or "",
        "steps": r.steps or "",
        "impact": r.impact or "",
        "remediation": r.remediation or "",
        "cwe": r.cwe or "",
        "cvss": r.cvss or "",
        "status": r.status,
    }


def serialize_recon_item(item: ReconItem) -> dict:
    tech_list = [t for t in (item.tech or "").split(",") if t]
    return {
        "id": item.id,
        "source": item.source or "",
        "url": item.url or "",
        "path": item.path or "",
        "host": item.host or "",
        "title": item.title or "",
        "status_code": item.status_code,
        "webserver": item.webserver or "",
        "port": item.port or "",
        "tech": tech_list,
        "content_type": item.content_type or "",
        "length": item.length,
        "words": item.words,
        "lines": item.lines,
        "notes": item.notes or "",
        "job_id": item.job_id,
    }


def serialize_scan_item(item: ScanItem) -> dict:
    return {
        "id": item.id,
        "source": item.source or "nuclei",
        "template_id": item.template_id or "",
        "title": item.title or "",
        "severity": item.severity or "info",
        "asset": item.asset or "",
        "matched_at": item.matched_at or "",
        "type": item.type or "",
        "description": item.description or "",
        "status": item.status or "new",
        "cwe": item.cwe or "",
        "cvss": item.cvss or "",
        "job_id": item.job_id,
    }


def serialize_import_record(r: ImportRecord) -> dict:
    return {
        "id": r.id,
        "tool_type": r.tool_type or "",
        "filename": r.filename or "redacted",
        "imported_count": r.imported_count or 0,
    }


_SEVERITIES = ["critical", "high", "medium", "low", "info"]
_FINDING_STATUSES = ["new", "candidate", "triaged", "in_progress", "closed"]


def serialize_engagement(p: Engagement, db: Session, github_id: str | None = None) -> dict:
    # Single query per table using COUNT aggregation — avoids N+1 on list endpoints.
    counts: dict[str, int] = {}
    for model, key in [
        (ReconItem,   "recon"),
        (ScanItem,    "scans"),
        (ManualTest,  "manual"),
        (Finding,     "findings"),
        (Report,      "reports"),
        (Service,     "services"),
    ]:
        row = db.query(func.count(model.id)).filter(model.program_id == p.id).scalar()  # type: ignore[attr-defined]
        counts[key] = row or 0

    sev_rows = (
        db.query(Finding.severity, func.count(Finding.id))
        .filter(Finding.program_id == p.id)
        .group_by(Finding.severity)
        .all()
    )
    findings_by_severity = {s: 0 for s in _SEVERITIES}
    for sev, cnt in sev_rows:
        if sev in findings_by_severity:
            findings_by_severity[sev] = cnt

    status_rows = (
        db.query(Finding.status, func.count(Finding.id))
        .filter(Finding.program_id == p.id)
        .group_by(Finding.status)
        .all()
    )
    findings_by_status = {s: 0 for s in _FINDING_STATUSES}
    for status, cnt in status_rows:
        if status in findings_by_status:
            findings_by_status[status] = cnt

    # Resolve through deps.engagement_access so ownership, organization
    # membership and per-engagement invitation are all honoured. Reading only
    # EngagementMember reported an org admin as "member", which is the role the
    # UI then uses to decide what to show.
    my_role = "owner"
    if github_id and github_id != p.owner_github_id:
        from deps import engagement_access

        my_role = engagement_access(p, github_id, db) or "viewer"

    return {
        "id": p.id,
        "owner_github_id": p.owner_github_id,
        "name": p.name,
        "platform": p.platform or "",
        "program_url": p.program_url or "",
        "scope_summary": p.scope_summary or "",
        "severity_guidance": p.severity_guidance or "",
        "safe_harbor_notes": p.safe_harbor_notes or "",
        "client_id":         p.client_id or "",
        "engagement_type":   p.engagement_type or "bug_bounty",
        "engagement_status": p.engagement_status or "active",
        "starts_at":         _iso(p.starts_at),
        "ends_at":           _iso(p.ends_at),
        # Surfaced so a client can show the brake is on without inferring it
        # from a denied request.
        "org_id":            p.org_id or "",
        "stop_work_at":      _iso(p.stop_work_at),
        "stop_work_reason":  p.stop_work_reason or "",
        "scope": {
            "in":  [serialize_scope_item(i) for i in p.scope_items if i.scope_type == "in"],
            "out": [serialize_scope_item(i) for i in p.scope_items if i.scope_type == "out"],
        },
        "imports":              [serialize_import_record(r) for r in p.import_records],
        "recon_count":          counts["recon"],
        "scans_count":          counts["scans"],
        "manual_tests_count":   counts["manual"],
        "findings_count":       counts["findings"],
        "findings_by_severity": findings_by_severity,
        "findings_by_status":   findings_by_status,
        "reports_count":        counts["reports"],
        "services_count":       counts["services"],
        "my_role":              my_role,
    }


def _iso(value) -> str:
    """Render a datetime as ISO-8601, or empty string when unset."""
    return value.isoformat() if value else ""


def serialize_client(c: Client) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "contact_name": c.contact_name or "",
        "contact_email": c.contact_email or "",
        "notes": c.notes or "",
        "created_at": _iso(c.created_at),
    }


def serialize_authorization(a: Authorization) -> dict:
    return {
        "id": a.id,
        "program_id": a.program_id,
        "permits": a.permits or "",
        "authorized_by": a.authorized_by or "",
        "authorized_at": _iso(a.authorized_at),
        "reference": a.reference or "",
        "window_start": _iso(a.window_start),
        "window_end": _iso(a.window_end),
        "status": a.status or "active",
        "notes": a.notes or "",
        "created_at": _iso(a.created_at),
    }
