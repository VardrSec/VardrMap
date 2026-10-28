"""Read-only authorization-testing coverage over the stored API inventory.

Joins four existing record kinds and nothing else: observed API operations
(`ApiEndpoint`), reviewed Gate cases (`AuthorizationTestCase`), executed Gate jobs
with their stored `assessment`, and the candidates/evidence those jobs produced.
It creates no table, infers no permission and judges nothing secure.

Semantics that must not drift:

* A case "covers" an operation only by a deterministic route match (same method,
  scheme, host, effective port and path shape). Identifier-shaped segments are
  normalised with the same rule inventory capture uses, and a `{placeholder}`
  segment in an inventory template matches exactly one concrete segment.
* "Executed" means a job reported an assessment. A finished job without one, a
  queued job and a failed job are not executions.
* `conclusive` repeats the stored assessment: every declared identity had a
  definite reported outcome and a working baseline. It is not evidence that the
  operation is secure, and candidates are reported alongside it, not hidden by it.
* An identity that exists elsewhere in the engagement but is absent from the
  cases covering an operation is reported as `not_reviewed`. That is a gap in
  what was reviewed, never a claim that the identity should have access.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from models import ApiEndpoint, ApiExchange, AuthorizationTestCase, Evidence, ScanItem, ScanJob
from routers.api_surface import infer_path_template

GATE_TOOL = "vardrgate_api_test"
STATES = (
    "violation_candidate",
    "inconclusive",
    "partial",
    "conclusive",
    "reviewed_not_executed",
    "untested",
)
# Order in which a researcher should look at operations: a flagged candidate, then what
# was never tested, then what ran without a definite answer, then what is settled.
STATE_ATTENTION = (
    "violation_candidate", "untested", "reviewed_not_executed", "inconclusive", "partial", "conclusive",
)
# Facts that make an authorization boundary worth testing first. Each is read from
# the stored inventory and is explained to the researcher; none is a verdict.
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
_OBJECT_SEGMENT = re.compile(r"^\{.+\}$")
_BOUNDARY_FIELDS = {
    "role", "roles", "is_admin", "admin", "permissions", "scope", "scopes",
    "tenant_id", "org_id", "organization_id", "account_id", "owner_id", "user_id",
    "price", "balance", "credit", "status",
}
# Scan item statuses (schemas.ScanStatus). A false positive is a closed question.
_OPEN_CANDIDATE = {"new", "reviewed"}
_IDENTITY_RANK = {"evaluated": 4, "inconclusive": 3, "missing": 2, "skipped": 1}


def _port(scheme: str, port: int | None) -> int:
    return port or (443 if scheme == "https" else 80)


def parse_request(request: object) -> dict | None:
    """The comparable shape of a case's request, or None when it is unusable."""
    if not isinstance(request, dict):
        return None
    method = str(request.get("method") or "").upper()
    try:
        url = urlsplit(str(request.get("url") or ""))
        port = url.port
    except ValueError:
        return None
    if not method or url.scheme not in {"http", "https"} or not url.hostname:
        return None
    return {
        "method": method,
        "scheme": url.scheme,
        "host": url.hostname.lower(),
        "port": _port(url.scheme, port),
        "template": infer_path_template(url.path or "/"),
    }


def _segments(template: str) -> list[str]:
    return [part for part in template.split("/") if part != ""]


def _template_matches(endpoint_template: str, case_template: str) -> bool:
    if endpoint_template == case_template:
        return True
    left, right = _segments(endpoint_template), _segments(case_template)
    if len(left) != len(right):
        return False
    return all(
        a == b or (a.startswith("{") and a.endswith("}")) or (b.startswith("{") and b.endswith("}"))
        for a, b in zip(left, right)
    )


def operation_matches(endpoint: ApiEndpoint, request: dict) -> bool:
    return (
        endpoint.method == request["method"]
        and (endpoint.scheme or "https") == request["scheme"]
        and (endpoint.host or "").lower() == request["host"]
        and _port(endpoint.scheme or "https", endpoint.port) == request["port"]
        and _template_matches(endpoint.path_template, request["template"])
    )


def _identity_ids(spec: dict) -> list[str]:
    ids = []
    for identity in spec.get("identities") or []:
        if isinstance(identity, dict) and identity.get("id"):
            ids.append(str(identity["id"]))
    return sorted(set(ids))


def _declared_decisions(spec: dict) -> dict[str, str]:
    decisions: dict[str, set[str]] = defaultdict(set)
    for item in spec.get("expected_access") or []:
        if isinstance(item, dict) and item.get("identity_id"):
            decisions[str(item["identity_id"])].add(str(item.get("decision") or "unknown"))
    # An identity with conflicting declarations has no single reviewed expectation.
    return {i: (next(iter(d)) if len(d) == 1 else "unknown") for i, d in decisions.items()}


def _latest(jobs: list[ScanJob]) -> ScanJob | None:
    executed = [j for j in jobs if j.assessment]
    if not executed:
        return None
    return max(executed, key=lambda j: (j.completed_at or j.created_at, j.created_at, j.id))


def build_coverage(db: Session, program_id: str) -> dict:
    endpoints = (
        db.query(ApiEndpoint)
        .filter(ApiEndpoint.program_id == program_id)
        .order_by(ApiEndpoint.host, ApiEndpoint.path_template, ApiEndpoint.method, ApiEndpoint.id)
        .all()
    )
    cases = (
        db.query(AuthorizationTestCase)
        .filter(AuthorizationTestCase.program_id == program_id)
        .order_by(AuthorizationTestCase.created_at, AuthorizationTestCase.id)
        .all()
    )
    jobs = (
        db.query(ScanJob)
        .filter(ScanJob.program_id == program_id, ScanJob.tool_type == GATE_TOOL)
        .all()
    )
    jobs_by_case: dict[str, list[ScanJob]] = defaultdict(list)
    for job in jobs:
        case_id = str((job.config or {}).get("test_case_id") or "")
        if case_id:
            jobs_by_case[case_id].append(job)
    job_ids = [j.id for j in jobs]
    candidates_by_job: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    evidence_by_job: dict[str, list[dict]] = defaultdict(list)
    if job_ids:
        for job_id, status in (
            db.query(ScanItem.job_id, ScanItem.status)
            .filter(ScanItem.program_id == program_id, ScanItem.source == "vardrgate", ScanItem.job_id.in_(job_ids))
            .all()
        ):
            candidates_by_job[job_id][status or "new"] += 1
        # Backing proof of a violation candidate: a reviewed deny that was observed
        # as an allow, retained as evidence for the same job.
        for row in (
            db.query(Evidence.id, Evidence.job_id, Evidence.case_id, Evidence.identity_id, Evidence.content_hash, Evidence.collected_at)
            .filter(
                Evidence.program_id == program_id,
                Evidence.job_id.in_(job_ids),
                Evidence.expected_decision == "deny",
                Evidence.observed_outcome == "allow",
            )
            .order_by(Evidence.collected_at, Evidence.id)
            .all()
        ):
            # Metadata only: the redacted record itself is read through the evidence endpoint.
            evidence_by_job[row.job_id].append({
                "evidence_id": row.id, "job_id": row.job_id, "case_id": row.case_id,
                "identity_id": row.identity_id, "content_hash": row.content_hash,
                "expected": "deny", "observed": "allow",
            })

    observed: dict[str, set[str]] = defaultdict(set)
    success_by: dict[str, set[str]] = defaultdict(set)
    fields_by: dict[str, set[str]] = defaultdict(set)
    for endpoint_id, label, status, names in db.query(
        ApiExchange.endpoint_id, ApiExchange.identity_label, ApiExchange.response_status, ApiExchange.parameter_names
    ).filter(ApiExchange.program_id == program_id).all():
        label = label or "anonymous"
        observed[endpoint_id].add(label)
        if status is not None and 200 <= status < 300:
            success_by[endpoint_id].add(label)
        for name in names or []:
            if str(name).lower() in _BOUNDARY_FIELDS:
                fields_by[endpoint_id].add(str(name).lower())

    case_rows = []
    unreviewed = []
    universe: set[str] = set()
    for case in cases:
        spec = case.spec if isinstance(case.spec, dict) else {}
        universe.update(_identity_ids(spec))
        if not any(d in {"allow", "deny"} for d in _declared_decisions(spec).values()):
            # A stored case with no allow/deny expectation reviews nothing yet.
            unreviewed.append(case)
            continue
        case_rows.append((case, spec, parse_request(spec.get("request"))))

    operations = []
    matched_case_ids: set[str] = set()
    for endpoint in endpoints:
        matched = [(c, s) for c, s, r in case_rows if r and operation_matches(endpoint, r)]
        matched_case_ids.update(c.id for c, _ in matched)
        operations.append(_operation(endpoint, matched, jobs_by_case, candidates_by_job, evidence_by_job, universe, sorted(observed.get(endpoint.id, ())), priority_reasons(endpoint, success_by.get(endpoint.id, set()), fields_by.get(endpoint.id, set()))))

    unmatched = [
        {
            "case_id": case.id,
            "name": case.name,
            "reason": "unusable_request" if request is None else "no_observed_operation",
            "request": None if request is None else f"{request['method']} {request['scheme']}://{request['host']}:{request['port']}{request['template']}",
        }
        for case, _, request in case_rows
        if case.id not in matched_case_ids
    ] + [
        {"case_id": case.id, "name": case.name, "reason": "no_reviewed_expectation", "request": None}
        for case in unreviewed
    ]
    counts = {state: 0 for state in STATES}
    for op in operations:
        counts[op["state"]] += 1
    return {
        "operations": operations,
        "summary": {"total": len(operations), **counts},
        "identities": sorted(universe),
        "unmatched_cases": unmatched,
    }


def priority_reasons(endpoint, success_identities: set[str], boundary_fields: set[str]) -> list[dict]:
    """Why an operation's authorization boundary may matter, from stored facts only."""
    reasons = []
    if any(_OBJECT_SEGMENT.match(part) for part in _segments(endpoint.path_template)):
        reasons.append({"code": "object_identifier_in_path", "detail": "The route addresses an object by identifier (object-level access)."})
    if endpoint.method in _STATE_CHANGING:
        reasons.append({"code": "state_changing_method", "detail": f"{endpoint.method} changes server state."})
    if boundary_fields:
        reasons.append({"code": "boundary_fields_in_requests", "detail": "Captured requests carry: " + ", ".join(sorted(boundary_fields)) + "."})
    if len(success_identities) >= 2:
        reasons.append({"code": "success_for_multiple_identities", "detail": "Captured 2xx responses for: " + ", ".join(sorted(success_identities)) + "."})
    if "anonymous" in success_identities:
        reasons.append({"code": "anonymous_success_observed", "detail": "A captured request without credentials returned 2xx."})
    return reasons


def _operation(endpoint, matched, jobs_by_case, candidates_by_job, evidence_by_job, universe, observed_identities, reasons) -> dict:
    case_entries = []
    executed_jobs: list[ScanJob] = []
    identity_state: dict[str, dict] = {}
    declared: dict[str, str] = {}
    for case, spec in matched:
        case_jobs = jobs_by_case.get(case.id, [])
        latest = _latest(case_jobs)
        queued = sum(1 for j in case_jobs if j.status in {"pending", "running"} and not j.assessment)
        decisions = _declared_decisions(spec)
        for identity in _identity_ids(spec):
            declared.setdefault(identity, decisions.get(identity, "unknown"))
        entry = {
            "case_id": case.id,
            "name": case.name,
            "test_case_id": case.test_case_id,
            "identities": _identity_ids(spec),
            "expected": decisions,
            "queued_jobs": queued,
            "executed": latest is not None,
            "latest_job_id": latest.id if latest else None,
            "assessment_status": (latest.assessment or {}).get("status") if latest else None,
            "reasons": list((latest.assessment or {}).get("reasons") or []) if latest else [],
        }
        case_entries.append(entry)
        if latest:
            executed_jobs.append(latest)
            for item in (latest.assessment or {}).get("identities") or []:
                identity = str(item.get("identity_id") or "")
                state = str(item.get("state") or "missing")
                best = identity_state.get(identity)
                if identity and (best is None or _IDENTITY_RANK.get(state, 0) > _IDENTITY_RANK.get(best["state"], 0)):
                    identity_state[identity] = {
                        "state": state,
                        "reason": str(item.get("reason") or ""),
                        "expected": str(item.get("expected_decision") or "unknown"),
                    }

    identity_rows = []
    for identity in sorted(universe):
        if identity in identity_state:
            identity_rows.append({"identity_id": identity, **identity_state[identity]})
        elif identity in declared:
            identity_rows.append(
                {"identity_id": identity, "state": "reviewed_not_run", "reason": "no_executed_assessment", "expected": declared[identity]}
            )
        else:
            identity_rows.append({"identity_id": identity, "state": "not_reviewed", "reason": "not_in_a_reviewed_case_for_this_operation", "expected": None})

    open_candidates = promoted = dismissed = 0
    backing_rows: list[dict] = []
    for job in executed_jobs:
        counts = candidates_by_job.get(job.id, {})
        open_candidates += sum(n for status, n in counts.items() if status in _OPEN_CANDIDATE)
        promoted += counts.get("promoted", 0)
        dismissed += counts.get("false_positive", 0)
        backing_rows.extend(evidence_by_job.get(job.id, []))

    statuses = [(j.assessment or {}).get("status") for j in executed_jobs]
    if not matched:
        state = "untested"
    elif not executed_jobs:
        state = "reviewed_not_executed"
    elif open_candidates or promoted:
        state = "violation_candidate"
    elif all(s == "conclusive" for s in statuses) and all(e["executed"] for e in case_entries):
        state = "conclusive"
    elif any(s in {"conclusive", "partial"} for s in statuses):
        state = "partial"
    else:
        state = "inconclusive"
    return {
        "endpoint_id": endpoint.id,
        "method": endpoint.method,
        "scheme": endpoint.scheme,
        "host": endpoint.host,
        "port": endpoint.port,
        "path_template": endpoint.path_template,
        "observed_identities": observed_identities,
        "priority_reasons": reasons,
        "state": state,
        "cases": case_entries,
        "identity_coverage": identity_rows,
        "candidates": {"open": open_candidates, "promoted": promoted, "false_positive": dismissed, "backing_evidence": len(backing_rows)},
        "candidate_evidence": backing_rows[:10],
    }
