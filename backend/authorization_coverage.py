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
* A run is **current** coverage for a case only when the spec frozen at claim
  (`ScanJob.case_snapshot`) hashes to the case's present spec and the assessment
  verified that snapshot. Anything else is **historical**: it stays visible, keeps
  its findings, and is attributed to the operation its own snapshot exercised, but
  it never counts as coverage for a definition it did not run.
* Unresolved findings are not coverage. A candidate keeps its operation flagged
  even after the case that produced it was edited or deleted.
* `conclusive` repeats the stored assessment: every declared identity had a
  definite reported outcome and a working baseline. It is not evidence that the
  operation is secure. It requires every matching case to have a current,
  conclusive run.
* An identity evaluated by some matching cases but not all is `mixed`, never
  `evaluated`. An identity that exists elsewhere in the engagement but is absent
  from the cases covering an operation is `not_reviewed`: a gap in what was
  reviewed, never a claim that the identity should have access.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from assessments import case_hash
from models import ApiEndpoint, ApiExchange, AuthorizationTestCase, Evidence, ScanItem, ScanJob
from routers.api_surface import infer_path_template

GATE_TOOL = "vardrgate_api_test"
STATES = (
    "violation_candidate",
    "inconclusive",
    "partial",
    "conclusive",
    "reviewed_not_executed",
    "stale",
    "untested",
)
# Order in which a researcher should look at operations: a flagged candidate, then what
# was never tested, then what was reviewed but not run (or run only before it changed),
# then what ran without a definite answer, then what is settled.
STATE_ATTENTION = (
    "violation_candidate", "untested", "reviewed_not_executed", "stale", "inconclusive", "partial", "conclusive",
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
_HISTORY_LIMIT = 10


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


class _Run:
    """One executed Gate job and what its own frozen snapshot says it exercised."""

    def __init__(self, job: ScanJob):
        self.job = job
        self.case_id = str((job.config or {}).get("test_case_id") or "")
        snapshot = job.case_snapshot if isinstance(job.case_snapshot, dict) and job.case_snapshot else None
        self.request = parse_request(snapshot.get("request")) if snapshot else None
        self.snapshot_hash = case_hash(snapshot) if snapshot else None
        self.verified = bool((job.assessment or {}).get("case_snapshot_verified"))

    def is_current_for(self, case_id: str, current_hash: str | None) -> bool:
        return bool(
            self.case_id == case_id
            and current_hash
            and self.verified
            and self.snapshot_hash == current_hash
        )


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
    case_by_id = {c.id: c for c in cases}
    current_hash = {
        c.id: (case_hash(c.spec) if isinstance(c.spec, dict) and c.spec else None) for c in cases
    }
    runs = [_Run(j) for j in jobs if j.assessment]
    runs_by_case: dict[str, list[_Run]] = defaultdict(list)
    for run in runs:
        runs_by_case[run.case_id].append(run)
    queued_by_case: dict[str, int] = defaultdict(int)
    for job in jobs:
        if job.status in {"pending", "running"} and not job.assessment:
            queued_by_case[str((job.config or {}).get("test_case_id") or "")] += 1

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
    attributed_run_ids: set[str] = set()
    for endpoint in endpoints:
        matched = [(c, s) for c, s, r in case_rows if r and operation_matches(endpoint, r)]
        matched_case_ids.update(c.id for c, _ in matched)
        # Runs are attributed by the request they actually executed, not by the case's
        # present definition, so history and findings stay on the operation they hit.
        attributed = [run for run in runs if run.request and operation_matches(endpoint, run.request)]
        attributed_run_ids.update(run.job.id for run in attributed)
        operations.append(_operation(
            endpoint, matched, attributed, runs_by_case, case_by_id, current_hash, queued_by_case,
            candidates_by_job, evidence_by_job, universe, sorted(observed.get(endpoint.id, ())),
            priority_reasons(endpoint, success_by.get(endpoint.id, set()), fields_by.get(endpoint.id, set())),
        ))

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
    # Executed runs whose own snapshot is missing or matches no observed operation can
    # not be placed anywhere. They are listed, never silently dropped.
    unattributed = [
        {"job_id": run.job.id, "case_id": run.case_id or None,
         "assessment_status": (run.job.assessment or {}).get("status"),
         "reason": "no_usable_snapshot" if run.request is None else "no_observed_operation"}
        for run in runs
        if run.job.id not in attributed_run_ids
    ]
    counts = {state: 0 for state in STATES}
    for op in operations:
        counts[op["state"]] += 1
    return {
        "operations": operations,
        "summary": {"total": len(operations), **counts},
        "identities": sorted(universe),
        "unmatched_cases": unmatched,
        "unattributed_assessments": unattributed,
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


def _historical_reason(run: _Run, case_by_id: dict) -> str:
    if run.case_id not in case_by_id:
        return "case_deleted"
    if not run.verified:
        return "snapshot_unverified"
    return "case_modified"


def _operation(
    endpoint, matched, attributed, runs_by_case, case_by_id, current_hash, queued_by_case,
    candidates_by_job, evidence_by_job, universe, observed_identities, reasons,
) -> dict:
    case_entries = []
    current_jobs: list[ScanJob] = []
    declared: dict[str, list[str]] = defaultdict(list)  # identity -> declaring case ids
    per_case_identity: dict[str, dict[str, dict | None]] = defaultdict(dict)
    stale_runs_for_matched = 0
    current_run_ids: set[str] = set()

    for case, spec in matched:
        # Every run of this case, wherever its old definition pointed: a case edited since
        # it last ran has history but no current coverage.
        mine = runs_by_case.get(case.id, [])
        current = [r.job for r in mine if r.is_current_for(case.id, current_hash.get(case.id))]
        stale = [r for r in mine if not r.is_current_for(case.id, current_hash.get(case.id))]
        stale_runs_for_matched += len(stale)
        latest = _latest(current)
        decisions = _declared_decisions(spec)
        identities = _identity_ids(spec)
        case_entries.append({
            "case_id": case.id,
            "name": case.name,
            "test_case_id": case.test_case_id,
            "identities": identities,
            "expected": decisions,
            "queued_jobs": queued_by_case.get(case.id, 0),
            "executed": latest is not None,
            "identity_states": {},
            "stale_runs": len(stale),
            "latest_job_id": latest.id if latest else None,
            "assessment_status": (latest.assessment or {}).get("status") if latest else None,
            "reasons": list((latest.assessment or {}).get("reasons") or []) if latest else [],
        })
        rows = {}
        if latest:
            current_jobs.append(latest)
            current_run_ids.add(latest.id)
            for item in (latest.assessment or {}).get("identities") or []:
                if item.get("identity_id"):
                    rows[str(item["identity_id"])] = {
                        "state": str(item.get("state") or "missing"),
                        "reason": str(item.get("reason") or ""),
                        "expected": str(item.get("expected_decision") or "unknown"),
                    }
        case_entries[-1]["identity_states"] = {i: rows[i]["state"] for i in identities if i in rows}
        for identity in identities:
            declared[identity].append(case.id)
            per_case_identity[identity][case.id] = (
                rows.get(identity, {"state": "missing", "reason": "execution_missing", "expected": decisions.get(identity, "unknown")})
                if latest else None
            )

    identity_rows = []
    for identity in sorted(universe):
        cells = [per_case_identity[identity].get(case_id) for case_id in declared.get(identity, [])]
        ran = [c for c in cells if c is not None]
        if not declared.get(identity):
            identity_rows.append({"identity_id": identity, "state": "not_reviewed", "reason": "not_in_a_reviewed_case_for_this_operation", "expected": None})
        elif not ran:
            reason = "case_changed_since_last_run" if stale_runs_for_matched else "no_executed_assessment"
            identity_rows.append({"identity_id": identity, "state": "reviewed_not_run", "reason": reason, "expected": None})
        else:
            expectations = {c["expected"] for c in ran}
            expected = next(iter(expectations)) if len(expectations) == 1 else "varies"
            evaluated = [c for c in ran if c["state"] == "evaluated"]
            if len(evaluated) == len(cells):
                identity_rows.append({"identity_id": identity, "state": "evaluated", "reason": evaluated[0]["reason"], "expected": expected})
            elif evaluated:
                identity_rows.append({"identity_id": identity, "state": "mixed", "reason": "evaluated_in_some_cases_only", "expected": expected})
            else:
                best = max(ran, key=lambda c: _IDENTITY_RANK.get(c["state"], 0))
                identity_rows.append({"identity_id": identity, "state": best["state"], "reason": best["reason"], "expected": expected})

    # Current coverage comes only from current runs; findings and history come from every
    # run that exercised this route, whatever has happened to its case since.
    open_candidates = promoted = dismissed = 0
    backing_rows: list[dict] = []
    history = []
    for run in attributed:
        counts = candidates_by_job.get(run.job.id, {})
        run_open = sum(n for status, n in counts.items() if status in _OPEN_CANDIDATE)
        open_candidates += run_open
        promoted += counts.get("promoted", 0)
        dismissed += counts.get("false_positive", 0)
        backing_rows.extend(evidence_by_job.get(run.job.id, []))
        if not any(run.is_current_for(c.id, current_hash.get(c.id)) for c, _ in matched):
            case = case_by_id.get(run.case_id)
            history.append({
                "job_id": run.job.id,
                "case_id": run.case_id or None,
                "case_name": case.name if case else None,
                "reason": _historical_reason(run, case_by_id),
                "assessment_status": (run.job.assessment or {}).get("status"),
                "completed_at": run.job.completed_at.isoformat() if run.job.completed_at else None,
                "candidates": {"open": run_open, "promoted": counts.get("promoted", 0), "false_positive": counts.get("false_positive", 0)},
            })
    history.sort(key=lambda h: (h["completed_at"] or "", h["job_id"]), reverse=True)

    statuses = [(j.assessment or {}).get("status") for j in current_jobs]
    if open_candidates or promoted:
        state = "violation_candidate"
    elif not matched:
        state = "untested"
    elif not current_jobs:
        state = "stale" if stale_runs_for_matched else "reviewed_not_executed"
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
        "historical_assessments": history[:_HISTORY_LIMIT],
    }
