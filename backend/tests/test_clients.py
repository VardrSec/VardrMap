"""Client CRUD, ownership isolation, and engagement detachment on delete."""


def _make_client(client, headers, name="Acme Corp", **extra):
    res = client.post("/clients", json={"name": name, **extra}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_create_client(client, auth_headers):
    res = client.post(
        "/clients",
        json={"name": "Acme Corp", "contact_name": "Dana Lee", "contact_email": "dana@acme.com"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Acme Corp"
    assert data["contact_name"] == "Dana Lee"
    assert "id" in data
    client.delete(f"/clients/{data['id']}", headers=auth_headers)


def test_create_client_requires_a_name(client, auth_headers):
    res = client.post("/clients", json={"name": ""}, headers=auth_headers)
    assert res.status_code == 422


def test_list_returns_only_own_clients(client, auth_headers, other_headers):
    mine = _make_client(client, auth_headers, "Mine")
    theirs = _make_client(client, other_headers, "Theirs")

    ids = [c["id"] for c in client.get("/clients", headers=auth_headers).json()]
    assert mine in ids
    assert theirs not in ids

    client.delete(f"/clients/{mine}", headers=auth_headers)
    client.delete(f"/clients/{theirs}", headers=other_headers)


def test_unauthenticated_is_rejected(client):
    assert client.get("/clients").status_code == 401
    assert client.post("/clients", json={"name": "X"}).status_code == 401


def test_get_other_users_client_returns_404(client, auth_headers, other_headers):
    """Cross-user access must not confirm the record exists."""
    cid = _make_client(client, auth_headers)
    assert client.get(f"/clients/{cid}", headers=other_headers).status_code == 404
    client.delete(f"/clients/{cid}", headers=auth_headers)


def test_patch_other_users_client_returns_404(client, auth_headers, other_headers):
    cid = _make_client(client, auth_headers)
    res = client.patch(f"/clients/{cid}", json={"name": "Hijacked"}, headers=other_headers)
    assert res.status_code == 404
    assert client.get(f"/clients/{cid}", headers=auth_headers).json()["name"] == "Acme Corp"
    client.delete(f"/clients/{cid}", headers=auth_headers)


def test_delete_other_users_client_returns_404(client, auth_headers, other_headers):
    cid = _make_client(client, auth_headers)
    assert client.delete(f"/clients/{cid}", headers=other_headers).status_code == 404
    assert client.get(f"/clients/{cid}", headers=auth_headers).status_code == 200
    client.delete(f"/clients/{cid}", headers=auth_headers)


def test_update_client(client, auth_headers):
    cid = _make_client(client, auth_headers)
    res = client.patch(f"/clients/{cid}", json={"contact_name": "New Contact"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["contact_name"] == "New Contact"
    assert res.json()["name"] == "Acme Corp"  # untouched fields survive
    client.delete(f"/clients/{cid}", headers=auth_headers)


def test_delete_client_detaches_but_does_not_delete_engagements(client, auth_headers):
    """The testing record outlives the commercial relationship."""
    cid = _make_client(client, auth_headers)
    prog = client.post(
        "/programs", json={"name": "Engagement", "client_id": cid}, headers=auth_headers
    ).json()
    pid = prog["id"]

    assert client.delete(f"/clients/{cid}", headers=auth_headers).status_code == 204

    still_there = client.get(f"/programs/{pid}", headers=auth_headers)
    assert still_there.status_code == 200, "deleting a client must not delete its engagements"

    client.delete(f"/programs/{pid}", headers=auth_headers)


def test_missing_client_returns_404(client, auth_headers):
    assert client.get("/clients/does-not-exist", headers=auth_headers).status_code == 404
