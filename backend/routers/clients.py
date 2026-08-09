"""Clients — the organisations engagements are performed for.

Scoped to the authenticated user like every other resource: a client belongs to
whoever created it, and another user asking for it gets 404 rather than 403, so
existence is never confirmed.

Clients are not shared through EngagementMember. Membership grants access to a
engagement, not to the client record behind it, which may cover other engagements
the member has nothing to do with.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, log_action
from models import Client, Engagement
from schemas import ClientCreate, ClientUpdate
from serializers import serialize_client

router = APIRouter()


def _get_client_or_404(client_id: str, current_user: dict[str, str], db: Session) -> Client:
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.owner_github_id == current_user["github_id"],
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/clients")
def list_clients(
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clients = db.query(Client).filter(
        Client.owner_github_id == current_user["github_id"],
    ).order_by(Client.name).all()
    return [serialize_client(c) for c in clients]


@router.post("/clients", status_code=201)
def create_client(
    payload: ClientCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = Client(
        owner_github_id=current_user["github_id"],
        name=payload.name,
        contact_name=payload.contact_name or "",
        contact_email=payload.contact_email or "",
        notes=payload.notes or "",
    )
    db.add(client)
    db.flush()
    log_action(db, current_user["github_id"], "create", "client", client.id)
    db.commit()
    db.refresh(client)
    return serialize_client(client)


@router.get("/clients/{client_id}")
def get_client(
    client_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_client(_get_client_or_404(client_id, current_user, db))


@router.patch("/clients/{client_id}")
def update_client(
    client_id: str,
    payload: ClientUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = _get_client_or_404(client_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(client, field, value)
    log_action(db, current_user["github_id"], "update", "client", client.id)
    db.commit()
    db.refresh(client)
    return serialize_client(client)


@router.delete("/clients/{client_id}", status_code=204)
def delete_client(
    client_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = _get_client_or_404(client_id, current_user, db)
    # Deleting a client must not delete its engagements — the testing record
    # outlives the commercial relationship. Detach instead.
    db.query(Engagement).filter(Engagement.client_id == client.id).update(
        {Engagement.client_id: None}, synchronize_session=False
    )
    db.delete(client)
    log_action(db, current_user["github_id"], "delete", "client", client_id)
    db.commit()
    return None
