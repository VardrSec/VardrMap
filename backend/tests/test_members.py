"""Engagement membership — invite collaborators, BOLA isolation, ownership guards."""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_program(client, headers, name="Shared Engagement"):
    res = client.post("/programs", json={"name": name}, headers=headers)
    assert res.status_code == 200
    return res.json()["id"]


def _cleanup(client, headers, program_id):
    client.delete(f"/programs/{program_id}", headers=headers)


# ---------------------------------------------------------------------------
# List + Add + Remove
# ---------------------------------------------------------------------------

def test_list_members_empty(client, auth_headers):
    pid = _create_program(client, auth_headers)
    res = client.get(f"/programs/{pid}/members", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["members"] == []
    assert res.json()["owner_github_id"] == "gh_user1"
    _cleanup(client, auth_headers, pid)


def test_add_member(client, auth_headers):
    pid = _create_program(client, auth_headers)
    res = client.post(
        f"/programs/{pid}/members",
        json={"github_id": "gh_user2"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["member_github_id"] == "gh_user2"
    assert data["role"] == "member"
    _cleanup(client, auth_headers, pid)


def test_add_member_duplicate_409(client, auth_headers):
    pid = _create_program(client, auth_headers)
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)
    res = client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)
    assert res.status_code == 409
    _cleanup(client, auth_headers, pid)


def test_add_owner_as_member_400(client, auth_headers):
    pid = _create_program(client, auth_headers)
    res = client.post(f"/programs/{pid}/members", json={"github_id": "gh_user1"}, headers=auth_headers)
    assert res.status_code == 400
    _cleanup(client, auth_headers, pid)


def test_remove_member(client, auth_headers):
    pid = _create_program(client, auth_headers)
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)
    res = client.delete(f"/programs/{pid}/members/gh_user2", headers=auth_headers)
    assert res.status_code == 200
    listed = client.get(f"/programs/{pid}/members", headers=auth_headers).json()["members"]
    assert listed == []
    _cleanup(client, auth_headers, pid)


def test_remove_nonexistent_member_404(client, auth_headers):
    pid = _create_program(client, auth_headers)
    res = client.delete(f"/programs/{pid}/members/nobody", headers=auth_headers)
    assert res.status_code == 404
    _cleanup(client, auth_headers, pid)


# ---------------------------------------------------------------------------
# Member access
# ---------------------------------------------------------------------------

def test_member_can_get_program(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)

    res = client.get(f"/programs/{pid}", headers=other_headers)
    assert res.status_code == 200
    assert res.json()["id"] == pid
    _cleanup(client, auth_headers, pid)


def test_member_appears_in_list_programs(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers, name="Shared For List Test")
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)

    ids = [p["id"] for p in client.get("/programs", headers=other_headers).json()["programs"]]
    assert pid in ids
    _cleanup(client, auth_headers, pid)


def test_member_can_create_finding(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)

    res = client.post(
        f"/programs/{pid}/findings",
        json={"title": "Member Finding", "severity": "high"},
        headers=other_headers,
    )
    assert res.status_code == 200
    _cleanup(client, auth_headers, pid)


def test_member_cannot_patch_program(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)

    res = client.patch(f"/programs/{pid}", json={"name": "Hijacked"}, headers=other_headers)
    assert res.status_code == 403
    _cleanup(client, auth_headers, pid)


def test_member_cannot_delete_program(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)

    res = client.delete(f"/programs/{pid}", headers=other_headers)
    assert res.status_code == 403
    _cleanup(client, auth_headers, pid)


def test_member_cannot_add_another_member(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2"}, headers=auth_headers)

    res = client.post(
        f"/programs/{pid}/members",
        json={"github_id": "gh_user3"},
        headers=other_headers,
    )
    assert res.status_code == 403
    _cleanup(client, auth_headers, pid)


# ---------------------------------------------------------------------------
# BOLA
# ---------------------------------------------------------------------------

def test_non_member_cannot_see_program(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    # user2 not added as member
    res = client.get(f"/programs/{pid}", headers=other_headers)
    assert res.status_code == 404
    _cleanup(client, auth_headers, pid)


def test_non_member_cannot_list_members(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    res = client.get(f"/programs/{pid}/members", headers=other_headers)
    assert res.status_code == 404
    _cleanup(client, auth_headers, pid)


def test_non_member_cannot_add_member(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    res = client.post(
        f"/programs/{pid}/members",
        json={"github_id": "gh_user3"},
        headers=other_headers,
    )
    assert res.status_code == 404
    _cleanup(client, auth_headers, pid)


def test_no_auth_returns_401(client):
    res = client.get("/programs/any-id/members")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Viewer role
# ---------------------------------------------------------------------------

def test_add_member_with_viewer_role(client, auth_headers):
    pid = _create_program(client, auth_headers)
    res = client.post(
        f"/programs/{pid}/members",
        json={"github_id": "gh_user2", "role": "viewer"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["role"] == "viewer"
    _cleanup(client, auth_headers, pid)


def test_viewer_cannot_create_finding(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    client.post(
        f"/programs/{pid}/members",
        json={"github_id": "gh_user2", "role": "viewer"},
        headers=auth_headers,
    )
    res = client.post(
        f"/programs/{pid}/findings",
        json={"title": "Viewer Finding", "severity": "high"},
        headers=other_headers,
    )
    assert res.status_code == 403
    _cleanup(client, auth_headers, pid)


def test_viewer_can_read_findings(client, auth_headers, other_headers):
    pid = _create_program(client, auth_headers)
    client.post(
        f"/programs/{pid}/members",
        json={"github_id": "gh_user2", "role": "viewer"},
        headers=auth_headers,
    )
    res = client.get(f"/programs/{pid}/findings", headers=other_headers)
    assert res.status_code == 200
    _cleanup(client, auth_headers, pid)
