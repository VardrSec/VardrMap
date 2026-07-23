"""Tests for saved scan profiles CRUD + BOLA."""


def _create(client, headers, program_id, **over):
    body = {"name": "CVE sweep", "tool_type": "nuclei", "target_source": "recon",
            "config": {"severity": "high,critical", "templates": "cves"}}
    body.update(over)
    return client.post(f"/programs/{program_id}/scan-profiles", json=body, headers=headers)


def test_create_and_list_profile(client, auth_headers, program_id):
    res = _create(client, auth_headers, program_id)
    assert res.status_code == 201, res.text
    pid = res.json()["id"]
    listed = client.get(f"/programs/{program_id}/scan-profiles", headers=auth_headers)
    assert listed.status_code == 200
    ids = {p["id"] for p in listed.json()["profiles"]}
    assert pid in ids


def test_create_rejects_bad_config_key(client, auth_headers, program_id):
    res = _create(client, auth_headers, program_id, config={"nope": "x"})
    assert res.status_code == 400


def test_create_rejects_bad_tool(client, auth_headers, program_id):
    res = _create(client, auth_headers, program_id, tool_type="notatool")
    assert res.status_code == 400


def test_delete_profile(client, auth_headers, program_id):
    pid = _create(client, auth_headers, program_id).json()["id"]
    res = client.delete(f"/programs/{program_id}/scan-profiles/{pid}", headers=auth_headers)
    assert res.status_code == 200
    listed = client.get(f"/programs/{program_id}/scan-profiles", headers=auth_headers).json()["profiles"]
    assert pid not in {p["id"] for p in listed}


def test_list_requires_auth(client, program_id):
    assert client.get(f"/programs/{program_id}/scan-profiles").status_code == 401


def test_bola_other_user_cannot_list(client, other_headers, program_id):
    assert client.get(f"/programs/{program_id}/scan-profiles", headers=other_headers).status_code == 404


def test_bola_other_user_cannot_create(client, other_headers, program_id):
    assert _create(client, other_headers, program_id).status_code == 404


def test_delete_missing_profile_404(client, auth_headers, program_id):
    res = client.delete(f"/programs/{program_id}/scan-profiles/nonexistent", headers=auth_headers)
    assert res.status_code == 404
