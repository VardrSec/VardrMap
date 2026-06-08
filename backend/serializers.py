from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Finding, ImportRecord, ManualTest, Program, ReconItem, Report, ScanItem, ScopeItem


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


def serialize_program(p: Program, db: Session) -> dict:
    recon_count  = db.query(ReconItem).filter(ReconItem.program_id == p.id).count()
    scans_count  = db.query(ScanItem).filter(ScanItem.program_id == p.id).count()
    manual_count = db.query(ManualTest).filter(ManualTest.program_id == p.id).count()
    finding_count = db.query(Finding).filter(Finding.program_id == p.id).count()
    report_count  = db.query(Report).filter(Report.program_id == p.id).count()

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

    return {
        "id": p.id,
        "owner_github_id": p.owner_github_id,
        "name": p.name,
        "platform": p.platform or "",
        "program_url": p.program_url or "",
        "scope_summary": p.scope_summary or "",
        "severity_guidance": p.severity_guidance or "",
        "safe_harbor_notes": p.safe_harbor_notes or "",
        "scope": {
            "in":  [serialize_scope_item(i) for i in p.scope_items if i.scope_type == "in"],
            "out": [serialize_scope_item(i) for i in p.scope_items if i.scope_type == "out"],
        },
        "imports":              [serialize_import_record(r) for r in p.import_records],
        "recon_count":          recon_count,
        "scans_count":          scans_count,
        "manual_tests_count":   manual_count,
        "findings_count":       finding_count,
        "findings_by_severity": findings_by_severity,
        "findings_by_status":   findings_by_status,
        "reports_count":        report_count,
    }
