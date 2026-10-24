"""Agent proposals: inert scope/authorization/rate changes awaiting operator approval.

An MCP agent can *propose* a change through the VardrRunner MCP server, but the server
exposes no approve tool (VardrRunner ADR 0015). A proposal is created here as ``pending``
and does nothing until a human with a **full-access key** approves it, which is what applies
the change. Creating a proposal needs only member-write — it is inert — but approving or
rejecting one needs full scope, so a runner-scoped or prompt-injected agent can never apply
its own proposal.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from db import get_db
from deps import (
    get_current_user,
    get_engagement_or_404,
    log_action,
    parse_iso_datetime,
    require_full_scope,
    require_member_write,
)
from models import AgentProposal, Authorization, ScopeItem
from schemas import AuthorizationCreate, ProposalCreate, ScopeItemCreate
from serializers import serialize_proposal

router = APIRouter(tags=["proposals"])

# A full operator attention budget, not a security control. Beyond this the agent is told to
# wait for the operator to clear the queue rather than pile on more.
_MAX_PENDING = 100

_SEVERITIES = {"", "info", "low", "medium", "high", "critical"}
_AUTH_DATE_FIELDS = ("authorized_at", "window_start", "window_end")


def _validated_payload(kind: str, payload: dict) -> dict:
    """Return a clean, stored-ready payload for the kind, or raise 400. The same sanitisers
    the real scope/authorization endpoints use run here, so an approval later needs no
    re-sanitisation and a malicious value never reaches the database."""
    try:
        if kind in ("scope_in", "scope_out"):
            item = ScopeItemCreate(**payload)
            out = {"value": item.value, "kind": item.kind, "notes": item.notes or ""}
            sev = payload.get("max_severity", "")
            if sev not in _SEVERITIES:
                raise HTTPException(status_code=400, detail=f"max_severity must be one of {_SEVERITIES}")
            out["max_severity"] = sev
            return out
        if kind == "authorization":
            auth = AuthorizationCreate(**payload)
            for field in _AUTH_DATE_FIELDS:
                parse_iso_datetime(getattr(auth, field), field)  # raises 400 on a bad date
            return auth.model_dump()
        if kind == "rate_ceiling":
            raw = payload.get("rate")
            try:
                rate = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="rate_ceiling payload needs an integer `rate`")
            if not 1 <= rate <= 1000:
                raise HTTPException(status_code=400, detail="rate must be between 1 and 1000")
            return {"rate": rate}
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    raise HTTPException(status_code=400, detail=f"unknown proposal kind {kind!r}")


@router.get("/engagements/{program_id}/proposals")
def list_proposals(
    program_id: str,
    status: str | None = None,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List proposals for the engagement, newest first. `status` filters to pending/approved/
    rejected. Readable by any member, so the agent can see what is already pending."""
    engagement = get_engagement_or_404(program_id, current_user, db)
    query = db.query(AgentProposal).filter(AgentProposal.program_id == engagement.id)
    if status is not None:
        query = query.filter(AgentProposal.status == status)
    rows = query.order_by(AgentProposal.created_at.desc()).all()
    return {"proposals": [serialize_proposal(p) for p in rows]}


@router.post("/engagements/{program_id}/proposals", status_code=201)
def create_proposal(
    program_id: str,
    payload: ProposalCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a pending proposal. Inert — it changes nothing until an operator approves it,
    so member-write is enough and a runner-scoped key may call it."""
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)

    pending = (
        db.query(AgentProposal)
        .filter(AgentProposal.program_id == engagement.id, AgentProposal.status == "pending")
        .count()
    )
    if pending >= _MAX_PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"{_MAX_PENDING} proposals already await review; resolve some first",
        )

    clean = _validated_payload(payload.kind, payload.payload)
    proposal = AgentProposal(
        program_id=engagement.id,
        owner_github_id=engagement.owner_github_id,
        proposed_by=current_user.get("username") or current_user.get("github_id") or "",
        kind=payload.kind,
        payload=clean,
        reason=payload.reason or "",
        source=payload.source or "",
        status="pending",
    )
    db.add(proposal)
    db.flush()
    log_action(db, current_user["github_id"], "create", "agent_proposal", proposal.id, engagement.id)
    db.commit()
    db.refresh(proposal)
    return serialize_proposal(proposal)


def _proposal_or_404(program_id: str, proposal_id: str, current_user: dict, db: Session):
    engagement = get_engagement_or_404(program_id, current_user, db)
    proposal = (
        db.query(AgentProposal)
        .filter(AgentProposal.id == proposal_id, AgentProposal.program_id == engagement.id)
        .first()
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return engagement, proposal


def _apply(engagement, proposal: AgentProposal, db: Session) -> str:
    """Apply an approved proposal; return the id of any row it created, or "" for a rate change."""
    kind, payload = proposal.kind, proposal.payload or {}
    if kind in ("scope_in", "scope_out"):
        item = ScopeItem(
            program_id=engagement.id,
            scope_type="in" if kind == "scope_in" else "out",
            value=payload["value"],
            kind=payload.get("kind", "domain"),
            notes=payload.get("notes", ""),
            max_severity=payload.get("max_severity", ""),
        )
        db.add(item)
        db.flush()
        return item.id
    if kind == "authorization":
        dates = {f: parse_iso_datetime(payload.get(f), f) for f in _AUTH_DATE_FIELDS}
        auth = Authorization(
            program_id=engagement.id,
            owner_github_id=engagement.owner_github_id,
            permits=payload.get("permits", ""),
            authorized_by=payload.get("authorized_by", ""),
            reference=payload.get("reference", ""),
            notes=payload.get("notes", ""),
            status="active",
            **dates,
        )
        db.add(auth)
        db.flush()
        return auth.id
    if kind == "rate_ceiling":
        engagement.max_request_rate = int(payload["rate"])
        return ""
    raise HTTPException(status_code=400, detail=f"cannot apply unknown kind {kind!r}")


@router.post("/engagements/{program_id}/proposals/{proposal_id}/approve")
def approve_proposal(
    program_id: str,
    proposal_id: str,
    current_user: dict[str, str] = Depends(require_full_scope),
    db: Session = Depends(get_db),
):
    """Approve a pending proposal, applying the change. **Full-access key only** — this is the
    operator action an agent must not be able to take."""
    engagement, proposal = _proposal_or_404(program_id, proposal_id, current_user, db)
    require_member_write(engagement, current_user, db)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"proposal is already {proposal.status}")

    proposal.applied_resource_id = _apply(engagement, proposal, db)
    proposal.status = "approved"
    proposal.resolved_at = datetime.now(timezone.utc)
    proposal.resolved_by = current_user["github_id"]
    log_action(db, current_user["github_id"], "approve", "agent_proposal", proposal.id, engagement.id)
    db.commit()
    db.refresh(proposal)
    return serialize_proposal(proposal)


@router.post("/engagements/{program_id}/proposals/{proposal_id}/reject")
def reject_proposal(
    program_id: str,
    proposal_id: str,
    current_user: dict[str, str] = Depends(require_full_scope),
    db: Session = Depends(get_db),
):
    """Reject a pending proposal without applying it. Full-access key only."""
    engagement, proposal = _proposal_or_404(program_id, proposal_id, current_user, db)
    require_member_write(engagement, current_user, db)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"proposal is already {proposal.status}")

    proposal.status = "rejected"
    proposal.resolved_at = datetime.now(timezone.utc)
    proposal.resolved_by = current_user["github_id"]
    log_action(db, current_user["github_id"], "reject", "agent_proposal", proposal.id, engagement.id)
    db.commit()
    db.refresh(proposal)
    return serialize_proposal(proposal)
