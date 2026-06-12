"""Program CRUD and BOLA/IDOR ownership checks."""


def test_create_program(client, auth_headers):
    res = client.post("/programs", json={"name": "My Program", "platform": "HackerOne"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "My Program"
    assert data["platform"] == "HackerOne"
    assert "id" in data
    # Cleanup
    client.delete(f"/programs/{data['id']}", headers=auth_headers)


def test_list_programs_returns_only_own(client, auth_headers, other_headers):
    res1 = client.post("/programs", json={"name": "User1 Program"}, headers=auth_headers)
    res2 = client.post("/programs", json={"name": "User2 Program"}, headers=other_headers)
    pid1 = res1.json()["id"]
    pid2 = res2.json()["id"]

    programs = client.get("/programs", headers=auth_headers).json()["programs"]
    ids = [p["id"] for p in programs]
    assert pid1 in ids
    assert pid2 not in ids

    # Cleanup
    client.delete(f"/programs/{pid1}", headers=auth_headers)
    client.delete(f"/programs/{pid2}", headers=other_headers)


def test_get_own_program(client, auth_headers, program_id):
    res = client.get(f"/programs/{program_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == program_id


def test_get_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    # program_id belongs to user1 — user2 must not be able to read it
    res = client.get(f"/programs/{program_id}", headers=other_headers)
    assert res.status_code == 404


def test_update_program(client, auth_headers, program_id):
    res = client.patch(f"/programs/{program_id}", json={"name": "Updated Name"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["name"] == "Updated Name"


def test_update_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    res = client.patch(f"/programs/{program_id}", json={"name": "Hijacked"}, headers=other_headers)
    assert res.status_code == 404


def test_delete_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    res = client.delete(f"/programs/{program_id}", headers=other_headers)
    assert res.status_code == 404
    # program should still exist for the real owner
    assert client.get(f"/programs/{program_id}", headers=auth_headers).status_code == 200


def test_delete_own_program(client, auth_headers):
    res = client.post("/programs", json={"name": "To Delete"}, headers=auth_headers)
    pid = res.json()["id"]
    del_res = client.delete(f"/programs/{pid}", headers=auth_headers)
    assert del_res.status_code == 200
    assert client.get(f"/programs/{pid}", headers=auth_headers).status_code == 404


def test_auth_sync_creates_user(client, auth_headers):
    res = client.post("/auth/sync", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["github_id"] == "gh_user1"
    assert data["username"] == "user1"


def test_auth_sync_updates_existing_user(client, auth_headers):
    client.post("/auth/sync", headers=auth_headers)
    res = client.post("/auth/sync", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["username"] == "user1"


def test_program_findings_by_severity_populated(client, auth_headers, program_id):
    client.post(f"/programs/{program_id}/findings", json={"title": "High Finding", "severity": "high", "asset": "example.com", "status": "new"}, headers=auth_headers)
    client.post(f"/programs/{program_id}/findings", json={"title": "Low Finding", "severity": "low", "asset": "example.com", "status": "triaged"}, headers=auth_headers)
    res = client.get(f"/programs/{program_id}", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["findings_by_severity"]["high"] >= 1
    assert data["findings_by_severity"]["low"] >= 1
    assert data["findings_by_status"]["new"] >= 1
    assert data["findings_by_status"]["triaged"] >= 1
