"""Nonrefundable allocated wall-permission seconds, not measured consumption."""
from fastapi import HTTPException


def allocate(engagement, body):
    seconds = body.duration_seconds if body is not None else None
    if engagement.duration_limit is None:
        if seconds is not None:
            raise HTTPException(409, "explicit engagement duration policy required")
        return None
    if seconds is None:
        raise HTTPException(409, "duration policy requires a finite owned allocation")
    total = engagement.duration_allocated + seconds
    if total > engagement.duration_limit:
        raise HTTPException(409, "engagement duration allocation exhausted")
    engagement.duration_allocated = total
    return {"allocated_seconds": seconds, "total_allocated_seconds": total,
            "limit_seconds": engagement.duration_limit}
