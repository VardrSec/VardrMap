"""API key generation, listing, revocation, and dual-path auth."""


def test_generate_api_key(client, auth_headers):
    res = client.post("/auth/apikeys", json={"label": "Burp Suite"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["token"].startswith("vmap_")
    assert data["label"] == "Burp Suite"
    assert "id" in data
    # token is present in create response only
    client.delete(f"/auth/apikeys/{data['id']}", headers=auth_headers)


def test_api_key_authenticates(client, auth_headers):
    res = client.post("/auth/apikeys", json={}, headers=auth_headers)
    token  = res.json()["token"]
    key_id = res.json()["id"]

    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200

    client.delete(f"/auth/apikeys/{key_id}", headers=auth_headers)


def test_revoked_key_is_rejected(client, auth_headers):
    res = client.post("/auth/apikeys", json={}, headers=auth_headers)
    token  = res.json()["token"]
    key_id = res.json()["id"]

    client.delete(f"/auth/apikeys/{key_id}", headers=auth_headers)

    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401


def test_list_keys_only_own(client, auth_headers, other_headers):
    res    = client.post("/auth/apikeys", json={"label": "u1"}, headers=auth_headers)
    key_id = res.json()["id"]

    ids = [k["id"] for k in client.get("/auth/apikeys", headers=auth_headers).json()["keys"]]
    assert key_id in ids

    other_ids = [k["id"] for k in client.get("/auth/apikeys", headers=other_headers).json()["keys"]]
    assert key_id not in other_ids

    client.delete(f"/auth/apikeys/{key_id}", headers=auth_headers)


def test_revoke_other_users_key_returns_404(client, auth_headers, other_headers):
    res    = client.post("/auth/apikeys", json={}, headers=auth_headers)
    key_id = res.json()["id"]

    assert client.delete(f"/auth/apikeys/{key_id}", headers=other_headers).status_code == 404

    client.delete(f"/auth/apikeys/{key_id}", headers=auth_headers)


def test_plaintext_token_not_in_list(client, auth_headers):
    res    = client.post("/auth/apikeys", json={"label": "secret"}, headers=auth_headers)
    key_id = res.json()["id"]

    keys = client.get("/auth/apikeys", headers=auth_headers).json()["keys"]
    row  = next(k for k in keys if k["id"] == key_id)
    assert "token"    not in row
    assert "key_hash" not in row

    client.delete(f"/auth/apikeys/{key_id}", headers=auth_headers)


def test_max_keys_per_user(client, auth_headers):
    created = []
    for i in range(10):
        r = client.post("/auth/apikeys", json={"label": f"key{i}"}, headers=auth_headers)
        assert r.status_code == 200
        created.append(r.json()["id"])

    overflow = client.post("/auth/apikeys", json={}, headers=auth_headers)
    assert overflow.status_code == 400

    for kid in created:
        client.delete(f"/auth/apikeys/{kid}", headers=auth_headers)
