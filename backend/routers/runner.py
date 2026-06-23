"""
Runner heartbeat — VardrRunner posts its status; frontend polls to display
real connectivity, hostname, version, and tool availability in the Bridge.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_program_or_404
from limiter import limiter
from models import RunnerHeartbeat, ScopeItem
from security import strip_html
from serializers import serialize_program

router = APIRouter(tags=["runner"])

# Runner is considered "online" if a heartbeat was received within this window.
_ONLINE_TIMEOUT_SECONDS = 300  # 5 minutes


def _age_seconds(last_seen: datetime) -> float:
    """Return seconds since last_seen. Handles both naive (SQLite) and aware datetimes."""
    now = datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return (now - last_seen).total_seconds()


def _serialize(hb: RunnerHeartbeat) -> dict:
    age = _age_seconds(hb.last_seen)
    return {
        "online":    age < _ONLINE_TIMEOUT_SECONDS,
        "last_seen": hb.last_seen.isoformat(),
        "hostname":  hb.hostname  or "",
        "version":   hb.version   or "",
        "os":        hb.os_info   or "",
        "tools":     hb.tools     or {},
    }


class HeartbeatPayload(BaseModel):
    hostname: str = Field(default="", max_length=200)
    version:  str = Field(default="", max_length=100)
    os:       str = Field(default="", max_length=200)
    tools:    dict[str, dict] = Field(default_factory=dict)  # {"httpx": {"ok": true, "version": "v1.6.9"}, ...}

    @field_validator("hostname", "version", "os", mode="before")
    @classmethod
    def sanitize(cls, v): return strip_html(v) if v else ""


@router.get("/programs/{program_id}")
def get_program_for_runner(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read-only program fetch — registered here (outside require_full_scope) so
    runner-scoped keys can resolve scope/targets when executing jobs."""
    program = get_program_or_404(program_id, current_user, db)
    return serialize_program(program, db)


@router.get("/programs/{program_id}/scope")
def get_program_scope(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scope-only fetch for runners that only need the target list."""
    get_program_or_404(program_id, current_user, db)
    items = db.query(ScopeItem).filter(ScopeItem.program_id == program_id).all()
    in_scope  = [{"id": i.id, "value": i.value, "kind": i.kind, "notes": i.notes} for i in items if i.scope_type == "in"]
    out_scope = [{"id": i.id, "value": i.value, "kind": i.kind, "notes": i.notes} for i in items if i.scope_type == "out"]
    return {"in": in_scope, "out": out_scope}


@router.post("/runner/heartbeat")
@limiter.limit("60/minute")
def post_heartbeat(
    request: Request,
    body: HeartbeatPayload,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """VardrRunner posts its status here on startup and periodically during jobs run.

    Upserted per (user, hostname) so multiple machines — e.g. a laptop and an
    always-on VPS — each keep their own status row.
    """
    hb = (
        db.query(RunnerHeartbeat)
        .filter(
            RunnerHeartbeat.owner_github_id == current_user["github_id"],
            RunnerHeartbeat.hostname == body.hostname,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if hb:
        hb.version   = body.version
        hb.os_info   = body.os
        hb.tools     = body.tools
        hb.last_seen = now
    else:
        hb = RunnerHeartbeat(
            owner_github_id = current_user["github_id"],
            hostname  = body.hostname,
            version   = body.version,
            os_info   = body.os,
            tools     = body.tools,
            last_seen = now,
        )
        db.add(hb)
    db.commit()
    db.refresh(hb)
    return {"ok": True, "last_seen": hb.last_seen.isoformat()}


@router.get("/runner/status")
def get_runner_status(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Frontend polls this to check connected runners.

    `runners` lists every machine that has ever sent a heartbeat (newest first).
    The top-level fields mirror the most recently seen runner for backward
    compatibility; `online` is true if ANY runner is online.
    """
    rows = (
        db.query(RunnerHeartbeat)
        .filter(RunnerHeartbeat.owner_github_id == current_user["github_id"])
        .order_by(RunnerHeartbeat.last_seen.desc())
        .all()
    )
    if not rows:
        return {
            "online":    False,
            "last_seen": None,
            "hostname":  None,
            "version":   None,
            "os":        None,
            "tools":     {},
            "runners":   [],
        }
    runners = [_serialize(hb) for hb in rows]
    most_recent = runners[0]
    return {
        "online":    any(r["online"] for r in runners),
        "last_seen": most_recent["last_seen"],
        "hostname":  most_recent["hostname"],
        "version":   most_recent["version"],
        "os":        most_recent["os"],
        "tools":     most_recent["tools"],
        "runners":   runners,
    }
