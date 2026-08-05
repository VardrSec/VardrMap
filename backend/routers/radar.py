"""Target Radar — fetches public bug bounty engagement listings and surfaces new ones.

Supported sources (all require no auth):
  - bugcrowd: https://bugcrowd.com/programs.json
  - hackerone: https://hackerone.com/programs.json

On refresh, new programs (not yet seen for this user) are stored with is_new="1".
GET /radar marks all programs as seen (is_new="0") when the client fetches the list.
"""
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user
from models import RadarProgram
from security import validate_safe_url

router = APIRouter(tags=["radar"])


def _safe_radar_url(raw: str | None, fallback: str) -> str:
    """Neutralize untrusted platform URLs. Radar ingests third-party data that is
    rendered as a clickable link in the UI, so a hostile ``javascript:`` / ``data:``
    URL in a platform response must never reach an href. Returns the cleaned URL if
    it is a safe http(s) link, otherwise the constructed platform fallback."""
    try:
        return validate_safe_url(raw) or fallback
    except ValueError:
        return fallback

_SOURCES = {
    "bugcrowd":  "https://bugcrowd.com/programs.json",
    "hackerone": "https://hackerone.com/programs.json",
}
_FETCH_TIMEOUT = 15  # seconds


def _parse_bugcrowd(data: dict | list) -> list[dict]:
    """Parse Bugcrowd public programs response into normalized dicts."""
    programs = data if isinstance(data, list) else data.get("programs", [])
    result = []
    for p in programs:
        code = p.get("code") or p.get("handle") or ""
        name = p.get("name") or code
        if not code or not name:
            continue
        result.append({
            "platform_id": str(code),
            "name":        str(name)[:300],
            "url":         _safe_radar_url(p.get("program_url"), f"https://bugcrowd.com/{code}"),
            "max_payout":  p.get("max_payout") or p.get("maximum_payout"),
        })
    return result


def _parse_hackerone(data: dict | list) -> list[dict]:
    """Parse HackerOne public programs response into normalized dicts."""
    programs = data if isinstance(data, list) else data.get("programs", [])
    result = []
    for p in programs:
        handle = p.get("handle") or p.get("code") or ""
        name   = p.get("name") or handle
        if not handle or not name:
            continue
        attrs = p.get("attributes") or p
        result.append({
            "platform_id": str(handle),
            "name":        str(name)[:300],
            "url":         _safe_radar_url(attrs.get("url"), f"https://hackerone.com/{handle}"),
            "max_payout":  attrs.get("maximum_bounty") or attrs.get("max_payout"),
        })
    return result


_PARSERS = {"bugcrowd": _parse_bugcrowd, "hackerone": _parse_hackerone}


def _fetch_platform(platform: str) -> list[dict]:
    url = _SOURCES[platform]
    try:
        resp = httpx.get(url, timeout=_FETCH_TIMEOUT, follow_redirects=True,
                         headers={"User-Agent": "VardrMap/0.17 (+https://github.com/VardrSec)"})
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch {platform}: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error fetching {platform}: {exc}")
    return _PARSERS[platform](data)


def serialize_radar(r: RadarProgram) -> dict:
    return {
        "id":             r.id,
        "platform":       r.platform,
        "platform_id":    r.platform_id,
        "name":           r.name,
        "url":            r.url,
        "max_payout":     r.max_payout,
        "is_new":         r.is_new == "1",
        "discovered_at":  r.discovered_at.isoformat()  if r.discovered_at  else None,
        "last_fetched_at": r.last_fetched_at.isoformat() if r.last_fetched_at else None,
    }


@router.get("/radar")
def list_radar(
    platform: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return stored radar programs. Marks all as seen (is_new=False) after delivery."""
    query = db.query(RadarProgram).filter(
        RadarProgram.owner_github_id == current_user["github_id"]
    )
    if platform:
        query = query.filter(RadarProgram.platform == platform)
    rows = query.order_by(RadarProgram.discovered_at.desc()).all()
    result = [serialize_radar(r) for r in rows]

    # Mark all returned programs as seen
    for row in rows:
        if row.is_new == "1":
            row.is_new = "0"
    db.commit()

    new_count = sum(1 for r in result if r["is_new"])
    return {"programs": result, "total": len(result), "new_count": new_count}


@router.post("/radar/refresh")
def refresh_radar(
    platform: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch programs from platform APIs and store new ones.

    Supported platforms: bugcrowd, hackerone. Omit platform to fetch all.
    Programs already stored (matched by platform + platform_id) are updated
    in place (last_fetched_at refreshed). Genuinely new programs are inserted
    with is_new="1" so the radar badge can highlight them.
    """
    platforms = [platform] if platform else list(_SOURCES.keys())
    for p in platforms:
        if p not in _SOURCES:
            raise HTTPException(status_code=400, detail=f"Unknown platform '{p}'. Use: {list(_SOURCES)}")

    now = datetime.now(timezone.utc)
    total_new = 0
    total_updated = 0

    for plat in platforms:
        entries = _fetch_platform(plat)
        for entry in entries:
            existing = db.query(RadarProgram).filter(
                RadarProgram.owner_github_id == current_user["github_id"],
                RadarProgram.platform == plat,
                RadarProgram.platform_id == entry["platform_id"],
            ).first()
            if existing:
                existing.name           = entry["name"]
                existing.url            = entry["url"] or existing.url
                existing.max_payout     = entry["max_payout"]
                existing.last_fetched_at = now
                total_updated += 1
            else:
                db.add(RadarProgram(
                    owner_github_id=current_user["github_id"],
                    platform=plat,
                    platform_id=entry["platform_id"],
                    name=entry["name"],
                    url=entry["url"] or "",
                    max_payout=entry["max_payout"],
                    is_new="1",
                    discovered_at=now,
                    last_fetched_at=now,
                ))
                total_new += 1

    db.commit()
    return {"new": total_new, "updated": total_updated, "platforms": platforms}
