from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Authorization, Client, Finding, ImportRecord, ManualTest, Engagement, EngagementMember, OrganizationMember, ReconItem, Report, ScanItem, ScopeItem, Service


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
        # Documented in api.md and used to order the list endpoint, but omitted
        # here until now — clients could not show when a deliverable was drafted.
        "created_at": _iso(r.created_at),
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


_COUNTED = [
    (ReconItem,  "recon"),
    (ScanItem,   "scans"),
    (ManualTest, "manual"),
    (Finding,    "findings"),
    (Report,     "reports"),
    (Service,    "services"),
]


def _resolve_roles(
    engagements: list[Engagement], github_id: str, db: Session
) -> dict[str, str]:
    """Effective role per engagement id, in two queries for the whole page.

    Mirrors `deps.engagement_access` exactly, including precedence —
    **owner > organization role > direct engagement membership**, highest rank
    wins — but resolves the whole list at once.

    Doing this per engagement was the N+1 that survived the first pass at
    batching: ownership short-circuits before any query, so a caller who owns
    everything never pays for it, and the original query-count test used exactly
    such a caller. An invited member, a viewer, or an organization member paid
    two extra queries *per engagement*.
    """
    # Imported here, not at module scope, to keep the existing one-way import
    # direction (routers -> serializers -> models) intact. Once per page.
    from deps import ROLE_RANK

    if not engagements:
        return {}

    # Ownership needs no query — it is already on the row.
    roles: dict[str, list[str]] = {
        e.id: (["owner"] if e.owner_github_id == github_id else []) for e in engagements
    }

    # Only engagements the caller does not own need a lookup.
    unowned = [e for e in engagements if e.owner_github_id != github_id]
    if unowned:
        org_ids = {e.org_id for e in unowned if e.org_id}
        org_roles: dict[str, str] = {}
        if org_ids:
            org_roles = {
                org_id: role
                for org_id, role in db.query(
                    OrganizationMember.org_id, OrganizationMember.role
                )
                .filter(
                    OrganizationMember.org_id.in_(org_ids),
                    OrganizationMember.github_id == github_id,
                )
                .all()
            }

        member_roles = {
            program_id: role or "member"
            for program_id, role in db.query(
                EngagementMember.program_id, EngagementMember.role
            )
            .filter(
                EngagementMember.program_id.in_([e.id for e in unowned]),
                EngagementMember.member_github_id == github_id,
            )
            .all()
        }

        for e in unowned:
            if e.org_id and e.org_id in org_roles:
                roles[e.id].append(org_roles[e.org_id])
            if e.id in member_roles:
                roles[e.id].append(member_roles[e.id])

    # Same tie-break as engagement_access; no access falls back to viewer, which
    # is what the serializer reported before.
    return {
        eid: (max(found, key=lambda r: ROLE_RANK.get(r, 0)) if found else "viewer")
        for eid, found in roles.items()
    }


def serialize_engagements(
    engagements: list[Engagement], db: Session, github_id: str | None = None
) -> list[dict]:
    """Serialize many engagements with a fixed number of queries.

    The per-engagement version issued six COUNTs plus two GROUP BYs *each*, so
    `GET /engagements` cost roughly 8N aggregate queries — a user with twenty
    engagements paid a hundred and sixty round trips to render one list.

    Here each aggregate is one GROUP BY over the whole id set, so the query count
    is constant in the number of engagements. This is the single implementation:
    `serialize_engagement` delegates to it, so the list and detail endpoints
    cannot drift apart in shape.
    """
    if not engagements:
        return []

    ids = [e.id for e in engagements]

    # One grouped COUNT per child table instead of one COUNT per (table, engagement).
    counts: dict[str, dict[str, int]] = {key: {} for _, key in _COUNTED}
    for model, key in _COUNTED:
        rows = (
            db.query(model.program_id, func.count(model.id))  # type: ignore[attr-defined]
            .filter(model.program_id.in_(ids))  # type: ignore[attr-defined]
            .group_by(model.program_id)  # type: ignore[attr-defined]
            .all()
        )
        counts[key] = {pid: cnt for pid, cnt in rows}

    sev_by_engagement: dict[str, dict[str, int]] = {}
    for pid, sev, cnt in (
        db.query(Finding.program_id, Finding.severity, func.count(Finding.id))
        .filter(Finding.program_id.in_(ids))
        .group_by(Finding.program_id, Finding.severity)
        .all()
    ):
        if sev in _SEVERITIES:
            sev_by_engagement.setdefault(pid, {})[sev] = cnt

    status_by_engagement: dict[str, dict[str, int]] = {}
    for pid, status, cnt in (
        db.query(Finding.program_id, Finding.status, func.count(Finding.id))
        .filter(Finding.program_id.in_(ids))
        .group_by(Finding.program_id, Finding.status)
        .all()
    ):
        if status in _FINDING_STATUSES:
            status_by_engagement.setdefault(pid, {})[status] = cnt

    # Two queries for every role on the page, rather than two per engagement.
    role_by_id = _resolve_roles(engagements, github_id, db) if github_id else {}

    return [
        _engagement_dict(
            e,
            my_role=role_by_id.get(e.id, "owner"),
            counts={key: counts[key].get(e.id, 0) for _, key in _COUNTED},
            findings_by_severity={
                s: sev_by_engagement.get(e.id, {}).get(s, 0) for s in _SEVERITIES
            },
            findings_by_status={
                s: status_by_engagement.get(e.id, {}).get(s, 0) for s in _FINDING_STATUSES
            },
        )
        for e in engagements
    ]


def serialize_engagement(p: Engagement, db: Session, github_id: str | None = None) -> dict:
    """One engagement. Delegates so list and detail share exactly one shape."""
    return serialize_engagements([p], db, github_id=github_id)[0]


def _engagement_dict(
    p: Engagement,
    *,
    my_role: str,
    counts: dict[str, int],
    findings_by_severity: dict[str, int],
    findings_by_status: dict[str, int],
) -> dict:
    """Pure shaping. Every value it needs is resolved and passed in, so it issues
    no queries of its own — that is what keeps the list endpoint constant-query."""
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
