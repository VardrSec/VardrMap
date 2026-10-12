"""Organization viewers can read shared clients but cannot mutate them."""
import pytest
from db import SessionLocal
from models import Client, OrganizationMember


@pytest.fixture
def shared_client(client, auth_headers, other_headers):
    row = client.post("/clients", json={"name": "Shared client"}, headers=auth_headers).json()
    with SessionLocal() as db:
        stored = db.get(Client, row["id"])
        membership = OrganizationMember(org_id=stored.org_id, github_id="gh_user2", role="viewer")
        db.add(membership)
        db.commit()
        member_id = membership.id
    yield row["id"]
    with SessionLocal() as db:
        db.query(OrganizationMember).filter_by(id=member_id).delete()
        db.commit()
    client.delete(f"/clients/{row['id']}", headers=auth_headers)


def test_viewer_can_read_shared_client(client, other_headers, shared_client):
    assert client.get(f"/clients/{shared_client}", headers=other_headers).status_code == 200


@pytest.mark.parametrize("method,payload", [("PATCH", {"name": "Changed"}), ("DELETE", None)])
def test_viewer_cannot_change_shared_client(client, other_headers, shared_client, method, payload):
    response = client.request(method, f"/clients/{shared_client}", json=payload, headers=other_headers)
    assert response.status_code == 403
    assert client.get(f"/clients/{shared_client}", headers=other_headers).json()["name"] == "Shared client"


def test_org_member_can_update_shared_client(client, other_headers, shared_client):
    with SessionLocal() as db:
        stored = db.get(Client, shared_client)
        db.query(OrganizationMember).filter_by(org_id=stored.org_id, github_id="gh_user2").update({"role": "member"})
        db.commit()
    assert client.patch(f"/clients/{shared_client}", json={"name": "Changed"}, headers=other_headers).status_code == 200
