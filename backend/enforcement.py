"""Database-aware adapter over the pure policy evaluator.

`policy.py` decides; this module gathers the facts it needs from the ORM,
records the outcome, and turns a denial into an HTTP response. Keeping the two
apart is what lets the decision logic be tested exhaustively without a database.

Every denial is written to `audit_logs` with its reason code before the
exception is raised. A refused execution attempt is a security event in its own
right — more interesting than a successful one — and losing it because the
request 403'd would defeat the point of having the control.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import policy
from models import Authorization, AuditLog, Engagement, ScopeItem


def _scope_rules(program_id: str, db: Session) -> tuple[policy.ScopeRule, ...]:
    rows = (
        db.query(ScopeItem.value, ScopeItem.kind, ScopeItem.scope_type)
        .filter(ScopeItem.program_id == program_id)
        .all()
    )
    return tuple(
        policy.ScopeRule(value=value, kind=kind or "domain", excluded=(scope_type == "out"))
        for value, kind, scope_type in rows
        if value
    )


def _authorization(program_id: str, db: Session) -> Optional[policy.AuthorizationSnapshot]:
    """The engagement's governing authorization.

    An engagement may accumulate several records over its life (an extension, a
    re-scoped follow-up). The most recently created one governs; older records
    are history, not additional grants.
    """
    row = (
        db.query(Authorization)
        .filter(Authorization.program_id == program_id)
        .order_by(Authorization.created_at.desc())
        .first()
    )
    if row is None:
        return None
    return policy.AuthorizationSnapshot(
        status=row.status or "",
        window_start=row.window_start,
        window_end=row.window_end,
    )


def build_input(
    engagement: Engagement,
    capability: str,
    db: Session,
    now: Optional[datetime] = None,
) -> policy.PolicyInput:
    return policy.PolicyInput(
        engagement_status=engagement.engagement_status or "",
        engagement_type=engagement.engagement_type or "",
        target="",
        capability=capability,
        now=now or datetime.now(timezone.utc),
        stop_work=engagement.stop_work_at is not None,
        authorization=_authorization(engagement.id, db),
        scope_rules=_scope_rules(engagement.id, db),
    )


def record_denial(
    db: Session,
    github_id: str,
    program_id: str,
    resource_id: str,
    decision: policy.PolicyDecision,
) -> None:
    """Append the denial to the audit log. Committed by the caller path below."""
    db.add(
        AuditLog(
            github_id=github_id,
            action="deny",
            resource_type="execution",
            resource_id=resource_id,
            program_id=program_id,
            reason=decision.reason,
            detail=decision.detail[:500],
        )
    )


def enforce(
    db: Session,
    engagement: Engagement,
    capability: str,
    github_id: str,
    targets: Iterable[str],
    resource_id: str = "",
    now: Optional[datetime] = None,
) -> None:
    """Raise 403 unless every target is authorized. Audits the denial first.

    The denial is committed even though the request fails, so an operator can
    see what was attempted and refused. Raised as 403 rather than 404: the
    caller is a legitimate member of this engagement, so there is nothing to
    conceal — they are being told the action is not permitted, which is
    actionable information.
    """
    candidate = build_input(engagement, capability, db, now=now)
    decision = policy.evaluate_all(candidate, targets)
    if decision.allowed:
        return

    record_denial(db, github_id, engagement.id, resource_id or capability, decision)
    db.commit()
    raise HTTPException(
        status_code=403,
        detail={
            "error": "execution_denied",
            "reason": decision.reason,
            "message": decision.detail,
        },
    )
