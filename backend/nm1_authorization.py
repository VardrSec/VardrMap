"""Read-only NM-1 issuance adapter; deliberately unregistered as an API/MCP route.

Returns an unsigned operator review request. Runner's reference signer/validator
owns the shared contract logic; this module neither signs nor executes work.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import policy
from assessments import case_hash
from models import Authorization, AuthorizationTestCase, Engagement, ScanJob, ScopeItem
from sqlalchemy.orm import Session


class IssuanceRefused(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise IssuanceRefused(reason)


def _time(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def prepare_approval_request(db: Session, **arguments) -> dict:
    """Owner-session review wrapper; ordinary API credentials cannot approve."""
    actor = arguments.get("actor", {})
    _require(
        actor.get("auth_method") in {"local_session", "github_session"}
        and actor.get("scope") == "full",
        "operator_session_required",
    )
    return project_current_authority(db, **arguments)


def project_current_authority(
    db: Session,
    *,
    job_id: str,
    authorization_id: str,
    actor: dict,
    plan: dict,
    runner_id: str,
    authority_revision: int,
    expires_at: datetime,
    max_executions: int,
    max_duration_seconds: int,
    max_artifact_bytes: int,
    credential_grants: list[dict],
    now: datetime,
    job_statuses: tuple[str, ...] = ("pending",),
) -> dict:
    """Unsigned fact projection, also reused to recheck an existing signed approval.

    This function grants no human provenance. Review callers must first use the
    owner-session wrapper; runtime callers verify their stored operator receipt.
    """
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    _require(
        job is not None
        and job.status in job_statuses
        and job.tool_type == "vardrgate_api_test",
        "pending_gate_job_required",
    )
    engagement = db.query(Engagement).filter(Engagement.id == job.program_id).first()
    _require(
        engagement is not None and actor.get("github_id") == engagement.owner_github_id,
        "owner_approval_required",
    )
    _require(engagement.stop_work_at is None, "stop_work_active")
    authority = (
        db.query(Authorization)
        .filter(
            Authorization.id == authorization_id,
            Authorization.program_id == engagement.id,
        )
        .populate_existing()
        .first()
    )
    _require(
        authority is not None and authority.status == "active",
        "explicit_active_authority_required",
    )
    case = (
        db.query(AuthorizationTestCase)
        .filter(
            AuthorizationTestCase.id
            == str((job.config or {}).get("test_case_id") or ""),
            AuthorizationTestCase.program_id == engagement.id,
        )
        .populate_existing()
        .first()
    )
    _require(
        case is not None
        and plan.get("schema") == "vardr.execution-plan/1"
        and plan.get("profile") == "gate-fixed-http/1"
        and plan.get("case_hash") == case_hash(case.spec),
        "reviewed_case_binding_required",
    )
    _require(
        type(max_executions) is int
        and 1 <= max_executions <= 1000
        and type(authority_revision) is int
        and authority_revision >= 0,
        "invalid_allowance",
    )
    _require(
        now.tzinfo is not None and expires_at.tzinfo is not None and expires_at > now,
        "bounded_validity_required",
    )
    scope_rows = (
        db.query(ScopeItem)
        .filter(ScopeItem.program_id == engagement.id)
        .order_by(ScopeItem.id)
        .populate_existing()
        .all()
    )
    rules = tuple(
        policy.ScopeRule(
            value=r.value, kind=r.kind or "domain", excluded=r.scope_type == "out"
        )
        for r in scope_rows
    )
    narrowed = []
    for dispatch in plan.get("dispatches", []):
        request = dispatch["request"]
        decision = policy.evaluate(
            policy.PolicyInput(
                engagement_status=engagement.engagement_status,
                engagement_type=engagement.engagement_type,
                target=request["url"],
                capability=job.tool_type,
                now=now,
                stop_work=False,
                authorization=policy.AuthorizationSnapshot(
                    authority.status, authority.window_start, authority.window_end
                ),
                scope_rules=rules,
            )
        )
        _require(decision.allowed, "recorded_scope_or_window_denied")
        parsed = urlsplit(request["url"])
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host = parsed.hostname
        if ":" in host:
            host = "[" + host + "]"
        narrowed.append(
            {
                "origin": f"{parsed.scheme}://{host}:{port}",
                "path": parsed.path or "/",
                "method": request["method"],
                "excluded": False,
                "reason": "",
            }
        )
    _require(bool(narrowed), "empty_plan")
    start = authority.window_start or now
    end = authority.window_end or expires_at
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    _require(expires_at <= end, "approval_exceeds_authority_window")
    snapshot = {
        "authorization": {
            "id": authority.id,
            "status": authority.status,
            "permits": authority.permits,
            "authorized_by": authority.authorized_by,
            "reference": authority.reference,
            "window_start": _time(authority.window_start),
            "window_end": _time(authority.window_end),
        },
        "scope": [
            {"value": r.value, "kind": r.kind, "scope_type": r.scope_type}
            for r in scope_rows
        ],
        "engagement_id": engagement.id,
    }
    return {
        "schema": "vardr.map-issuance-request/1",
        "origin": "map",
        "approver_id": actor["github_id"],
        "authority_snapshot": snapshot,
        "case": case.spec,
        "context": {
            "runner_id": runner_id,
            "engagement_id": engagement.id,
            "job_id": job.id,
            "authority_revision": authority_revision,
            "authority_sha256": _digest(snapshot),
            "plan_sha256": _digest(plan),
            "mode": "strict",
            "scope": narrowed,
            "exceptions": [],
            "not_before": _time(now),
            "expires_at": _time(expires_at),
            "testing_start": _time(start),
            "testing_end": _time(end),
            "max_executions": max_executions,
            "max_duration_seconds": max_duration_seconds,
            "max_http_dispatches": plan["max_http_dispatches"],
            "max_artifact_bytes": max_artifact_bytes,
            "credential_grants": credential_grants,
            "control": "managed_online",
        },
    }
