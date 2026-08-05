"""Engagement CRUD and BOLA/IDOR ownership checks."""


def test_create_program(client, auth_headers):
    res = client.post("/programs", json={"name": "My Engagement", "platform": "HackerOne"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "My Engagement"
    assert data["platform"] == "HackerOne"
    assert "id" in data
    # Cleanup
    client.delete(f"/programs/{data['id']}", headers=auth_headers)


def test_list_programs_returns_only_own(client, auth_headers, other_headers):
    res1 = client.post("/programs", json={"name": "User1 Engagement"}, headers=auth_headers)
    res2 = client.post("/programs", json={"name": "User2 Engagement"}, headers=other_headers)
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
    # engagement should still exist for the real owner
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


# --- Engagement context (clients, type, status, dates) -----------------------


def test_program_defaults_to_bug_bounty(client, auth_headers):
    """An unmodified caller creates exactly what it created before."""
    res = client.post("/programs", json={"name": "Legacy Call"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["engagement_type"] == "bug_bounty"
    assert data["engagement_status"] == "active"
    assert data["client_id"] == ""
    client.delete(f"/programs/{data['id']}", headers=auth_headers)


def test_create_pentest_engagement_with_dates(client, auth_headers):
    res = client.post(
        "/programs",
        json={
            "name": "Q3 Web App Test",
            "engagement_type": "pentest",
            "engagement_status": "planned",
            "starts_at": "2026-09-01T09:00:00Z",
            "ends_at": "2026-09-14T17:00:00Z",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["engagement_type"] == "pentest"
    assert data["engagement_status"] == "planned"
    assert data["starts_at"].startswith("2026-09-01")
    client.delete(f"/programs/{data['id']}", headers=auth_headers)


def test_create_rejects_unknown_engagement_type(client, auth_headers):
    res = client.post(
        "/programs", json={"name": "X", "engagement_type": "freelance"}, headers=auth_headers
    )
    assert res.status_code == 422


def test_create_rejects_a_bad_date(client, auth_headers):
    res = client.post("/programs", json={"name": "X", "starts_at": "soon"}, headers=auth_headers)
    assert res.status_code == 422
    assert "ISO-8601" in res.text


def test_cannot_attach_another_users_client(client, auth_headers, other_headers):
    """client_id must not become an existence oracle for other users' records."""
    theirs = client.post("/clients", json={"name": "Their Client"}, headers=other_headers).json()["id"]

    res = client.post(
        "/programs", json={"name": "Mine", "client_id": theirs}, headers=auth_headers
    )
    assert res.status_code == 404

    client.delete(f"/clients/{theirs}", headers=other_headers)


def test_patch_engagement_fields(client, auth_headers, program_id):
    res = client.patch(
        f"/programs/{program_id}",
        json={"engagement_status": "reporting", "ends_at": "2026-12-31T00:00:00Z"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["engagement_status"] == "reporting"
    assert data["ends_at"].startswith("2026-12-31")


def test_patch_cannot_attach_another_users_client(client, auth_headers, other_headers, program_id):
    theirs = client.post("/clients", json={"name": "Theirs"}, headers=other_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}", json={"client_id": theirs}, headers=auth_headers)
    assert res.status_code == 404
    client.delete(f"/clients/{theirs}", headers=other_headers)
