from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_full_scope
from models import Service

router = APIRouter(tags=["services"])


class ServiceIn(BaseModel):
    host: str = Field(min_length=1, max_length=500)
    port: int = Field(ge=1, le=65535)
    protocol: str = Field(default="tcp", pattern="^(tcp|udp)$")
    service_name: Optional[str] = Field(default="", max_length=100)
    product: Optional[str] = Field(default="", max_length=200)
    version: Optional[str] = Field(default="", max_length=100)
    state: Optional[str] = Field(default="open", max_length=20)
    source: Optional[str] = Field(default="nmap", max_length=50)


class ServicesBulkCreate(BaseModel):
    services: list[ServiceIn] = Field(max_length=5000)


def serialize_service(s: Service) -> dict:
    return {
        "id":             s.id,
        "program_id":     s.program_id,
        "host":           s.host,
        "port":           s.port,
        "protocol":       s.protocol,
        "service_name":   s.service_name,
        "product":        s.product,
        "version":        s.version,
        "state":          s.state,
        "source":         s.source,
        "created_at":     s.created_at.isoformat()      if s.created_at      else None,
        "last_scanned_at": s.last_scanned_at.isoformat() if s.last_scanned_at else None,
    }


@router.get("/engagements/{program_id}/services")
def list_services(
    program_id: str,
    current_user: dict = Depends(require_full_scope),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    rows = (
        db.query(Service)
        .filter(Service.program_id == program_id)
        .order_by(Service.host, Service.port)
        .all()
    )
    return {"services": [serialize_service(s) for s in rows], "total": len(rows)}


@router.post("/engagements/{program_id}/services", status_code=201)
def bulk_create_services(
    program_id: str,
    body: ServicesBulkCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """VardrRunner posts nmap results here. Upserts on (host, port, protocol) — updates
    service metadata if the combination already exists rather than creating duplicates."""
    get_engagement_or_404(program_id, current_user, db)

    now = datetime.now(timezone.utc)
    created = 0
    updated = 0
    for svc in body.services:
        existing = (
            db.query(Service)
            .filter(
                Service.program_id == program_id,
                Service.host == svc.host,
                Service.port == svc.port,
                Service.protocol == svc.protocol,
            )
            .first()
        )
        if existing:
            existing.service_name    = svc.service_name or ""
            existing.product         = svc.product or ""
            existing.version         = svc.version or ""
            existing.state           = svc.state or "open"
            existing.source          = svc.source or "nmap"
            existing.last_scanned_at = now
            updated += 1
        else:
            db.add(Service(
                program_id=program_id,
                owner_github_id=current_user["github_id"],
                host=svc.host,
                port=svc.port,
                protocol=svc.protocol or "tcp",
                service_name=svc.service_name or "",
                product=svc.product or "",
                version=svc.version or "",
                state=svc.state or "open",
                source=svc.source or "nmap",
                last_scanned_at=now,
            ))
            created += 1

    # One audit entry per bulk upsert (not per service) to record who changed the
    # engagement's service inventory, without flooding the log.
    log_action(db, current_user["github_id"], "upsert", "service", program_id, program_id=program_id)
    db.commit()
    return {"created": created, "updated": updated}


@router.delete("/engagements/{program_id}/services/{service_id}", status_code=200)
def delete_service(
    program_id: str,
    service_id: str,
    current_user: dict = Depends(require_full_scope),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    svc = db.query(Service).filter(
        Service.id == service_id,
        Service.program_id == program_id,
    ).first()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    log_action(db, current_user["github_id"], "delete", "service", service_id, program_id=program_id)
    db.delete(svc)
    db.commit()
    return {"message": "Service deleted"}
