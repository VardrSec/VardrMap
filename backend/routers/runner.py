"""
Runner heartbeat — VardrRunner posts its status; frontend polls to display
real connectivity, hostname, version, and tool availability in the Bridge.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user
from limiter import limiter
from models import RunnerHeartbeat

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
    hostname: str = ""
    version:  str = ""
    os:       str = ""
    tools:    dict = {}  # {"httpx": {"ok": true, "version": "v1.6.9"}, ...}


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
