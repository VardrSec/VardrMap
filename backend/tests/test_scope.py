"""Scope item add/delete and BOLA/IDOR ownership checks."""

_IN_ITEM = {"value": "*.example.com", "kind": "subdomain", "notes": "main target"}
_OUT_ITEM = {"value": "admin.example.com", "kind": "subdomain", "notes": "out of scope"}


def test_add_in_scope_item(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["value"] == _IN_ITEM["value"]
    assert data["kind"] == _IN_ITEM["kind"]
    assert "id" in data


def test_add_in_scope_item_minimal(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/scope/in", json={"value": "example.com", "kind": "domain"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["notes"] == ""


def test_add_out_scope_item(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/scope/out", json=_OUT_ITEM, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["value"] == _OUT_ITEM["value"]


def test_delete_in_scope_item(client, auth_headers, program_id):
    item_id = client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/scope/in/{item_id}", headers=auth_headers)
    assert res.status_code == 200


def test_delete_out_scope_item(client, auth_headers, program_id):
    item_id = client.post(f"/programs/{program_id}/scope/out", json=_OUT_ITEM, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/scope/out/{item_id}", headers=auth_headers)
    assert res.status_code == 200


def test_delete_nonexistent_scope_item_returns_404(client, auth_headers, program_id):
    res = client.delete(f"/programs/{program_id}/scope/in/nonexistent", headers=auth_headers)
    assert res.status_code == 404


def test_delete_scope_item_wrong_scope_type_returns_400(client, auth_headers, program_id):
    item_id = client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/scope/invalid/{item_id}", headers=auth_headers)
    assert res.status_code == 400


def test_delete_in_item_via_out_path_returns_404(client, auth_headers, program_id):
    item_id = client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/scope/out/{item_id}", headers=auth_headers)
    assert res.status_code == 404


def test_scope_visible_on_program(client, auth_headers, program_id):
    client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM, headers=auth_headers)
    client.post(f"/programs/{program_id}/scope/out", json=_OUT_ITEM, headers=auth_headers)
    res = client.get(f"/programs/{program_id}", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert any(s["value"] == _IN_ITEM["value"] for s in data["scope"]["in"])
    assert any(s["value"] == _OUT_ITEM["value"] for s in data["scope"]["out"])


# BOLA checks

def test_add_in_scope_to_other_users_program_returns_404(client, other_headers, program_id):
    res = client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM, headers=other_headers)
    assert res.status_code == 404


def test_add_out_scope_to_other_users_program_returns_404(client, other_headers, program_id):
    res = client.post(f"/programs/{program_id}/scope/out", json=_OUT_ITEM, headers=other_headers)
    assert res.status_code == 404


def test_delete_scope_item_from_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    item_id = client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/scope/in/{item_id}", headers=other_headers)
    assert res.status_code == 404


# Auth checks

def test_add_scope_item_unauthorized(client, program_id):
    res = client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM)
    assert res.status_code == 401


def test_delete_scope_item_unauthorized(client, auth_headers, program_id):
    item_id = client.post(f"/programs/{program_id}/scope/in", json=_IN_ITEM, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/scope/in/{item_id}")
    assert res.status_code == 401
