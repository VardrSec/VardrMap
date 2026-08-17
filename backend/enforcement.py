"""Database-aware adapter over the pure policy evaluator.

`policy.py` decides; this module gathers the facts it needs from the ORM and
turns the decision into something a router can return. Keeping the two apart is
what lets the decision logic be tested exhaustively without a database.

**Scope findings are advisory.** VardrMap warns that a target falls outside the
recorded scope; it does not refuse to run. Staying inside scope is the
operator's responsibility, the same as it is with every other tool in the kit —
Burp and nmap do not police their users either, and a platform that guesses
wrong blocks legitimate work mid-engagement. The reason codes are unchanged, so
a caller that wants to treat a warning as fatal can.

The one exception is **stop-work**, which still refuses. That is not the
platform second-guessing the operator: it is the operator's own emergency brake,
pulled deliberately, and honouring it is the entire point of having it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import policy
from models import Authorization, Engagement, ScopeItem


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


def as_warnings(decision: Optional[policy.PolicyDecision]) -> list[dict]:
    """Render a decision as the `warnings` array routers return. Empty when allowed."""
    if decision is None or decision.allowed:
        return []
    return [{"reason": decision.reason, "message": decision.detail}]


def check(
    db: Session,
    engagement: Engagement,
    capability: str,
    targets: Iterable[str],
    now: Optional[datetime] = None,
) -> Optional[policy.PolicyDecision]:
    """Evaluate the engagement and its targets. Returns None when nothing is flagged.

    Raises 403 only for stop-work — the operator's own halt switch. Every other
    reason (out-of-scope target, closed testing window, missing authorization,
    inactive engagement) comes back as a decision for the caller to surface as a
    warning; the work is not blocked.
    """
    candidate = build_input(engagement, capability, db, now=now)
    decision = policy.evaluate_all(candidate, targets)
    if decision.allowed:
        return None

    if decision.reason == policy.STOP_WORK_ACTIVE:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "stop_work_active",
                "reason": decision.reason,
                "message": decision.detail,
            },
        )

    return decision
