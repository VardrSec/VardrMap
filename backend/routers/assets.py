"""Attack surface — the asset graph read API.

The query this exists to answer is "everything we know about this host", which
before the graph required a fuzzy string scan across four tables.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404
from models import Asset, AssetRelationship, Finding, ReconItem, ScanItem, Service

router = APIRouter(tags=["assets"])

MAX_LIMIT = 500


def _serialize(a: Asset) -> dict:
    return {
        "id": a.id,
        "canonical_key": a.canonical_key,
        "asset_type": a.asset_type,
        "label": a.label or "",
        "hostname": a.hostname or "",
        "ip": a.ip or "",
        "port": a.port,
        "scheme": a.scheme or "",
        "environment": a.environment or "",
        "criticality": a.criticality or "",
        "exposure": a.exposure or "",
        "tags": a.tags or "",
        "source": a.source or "",
        "confidence": a.confidence or "",
        "first_seen_at": a.first_seen_at.isoformat() if a.first_seen_at else "",
        "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else "",
    }


@router.get("/engagements/{program_id}/assets")
def list_assets(
    program_id: str,
    asset_type: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)

    query = db.query(Asset).filter(Asset.program_id == program_id)
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if q:
        # Prefix match on the indexed hostname column. Deliberately not a
        # leading-wildcard LIKE, which would scan the table.
        query = query.filter(Asset.hostname.startswith(q.lower()))

    total = query.count()
    rows = query.order_by(Asset.hostname.asc(), Asset.port.asc()).offset(offset).limit(limit).all()
    return {"assets": [_serialize(a) for a in rows], "total": total}


@router.get("/engagements/{program_id}/assets/{asset_id}")
def get_asset(
    program_id: str,
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One asset with everything joined to it — the query the graph exists for."""
    get_engagement_or_404(program_id, current_user, db)
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.program_id == program_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    edges = (
        db.query(AssetRelationship)
        .filter(
            (AssetRelationship.src_asset_id == asset_id)
            | (AssetRelationship.dst_asset_id == asset_id)
        )
        .all()
    )
    neighbour_ids = {e.src_asset_id for e in edges} | {e.dst_asset_id for e in edges}
    neighbour_ids.discard(asset_id)
    neighbours = (
        {a.id: a for a in db.query(Asset).filter(Asset.id.in_(neighbour_ids)).all()}
        if neighbour_ids else {}
    )

    return {
        "asset": _serialize(asset),
        "relationships": [
            {
                "relationship": e.relationship,
                "direction": "out" if e.src_asset_id == asset_id else "in",
                "other": _serialize(neighbours[other])
                if (other := (e.dst_asset_id if e.src_asset_id == asset_id else e.src_asset_id))
                in neighbours
                else None,
                "confidence": e.confidence or "",
                "source": e.source or "",
            }
            for e in edges
        ],
        "counts": {
            "recon": db.query(ReconItem).filter(ReconItem.asset_id == asset_id).count(),
            "scans": db.query(ScanItem).filter(ScanItem.asset_id == asset_id).count(),
            "services": db.query(Service).filter(Service.asset_id == asset_id).count(),
            "findings": db.query(Finding).filter(Finding.asset_id == asset_id).count(),
        },
    }
