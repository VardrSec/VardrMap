"""A viewer-role member may read an engagement but must not write anything.

Setup: owner (gh_user1) creates an engagement and invites gh_user2 as a "viewer".
gh_user2's headers are `other_headers`. Every write must return 403; reads 200.
The write guard (`require_member_write`) fires before any resource lookup, so a
403 is expected even when the target id does not exist.
"""
import io

import pytest


@pytest.fixture
def viewer_program(client, auth_headers):
    """Engagement owned by gh_user1 with gh_user2 invited as a viewer. Yields its id."""
    pid = client.post("/programs", json={"name": "Viewer Engagement"}, headers=auth_headers).json()["id"]
    res = client.post(
        f"/programs/{pid}/members",
        json={"github_id": "gh_user2", "role": "viewer"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["role"] == "viewer"
    yield pid
    client.delete(f"/programs/{pid}", headers=auth_headers)


# --------------------------------------------------------------------------- #
# Reads are allowed
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", [
    "", "/findings", "/scans", "/recon", "/manual-tests", "/reports",
    "/submissions", "/schedules", "/scan-profiles", "/services", "/jobs", "/members",
])
def test_viewer_can_read(client, other_headers, viewer_program, path):
    res = client.get(f"/programs/{viewer_program}{path}", headers=other_headers)
    assert res.status_code == 200, f"viewer should be able to GET {path or '/'} -> {res.status_code}"


# --------------------------------------------------------------------------- #
# Writes are forbidden (403)
# --------------------------------------------------------------------------- #

def _post(client, headers, url, body):
    return client.post(url, json=body, headers=headers)


def test_viewer_cannot_queue_job(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/jobs",
                {"tool_type": "nuclei", "target_source": "scope"})
    assert res.status_code == 403


def test_viewer_cannot_queue_pipeline(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/pipelines",
                {"stages": [{"tool_type": "subfinder", "target_source": "scope"}]})
    assert res.status_code == 403


def test_viewer_cannot_create_scan_profile(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/scan-profiles",
                {"name": "x", "tool_type": "nuclei", "target_source": "scope"})
    assert res.status_code == 403


def test_viewer_cannot_triage_scans(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/scans/triage", {"ids": []})
    assert res.status_code == 403


def test_viewer_cannot_create_manual_test(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/manual-tests", {"title": "t"})
    assert res.status_code == 403


def test_viewer_cannot_create_finding(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/findings",
                {"title": "t", "severity": "low", "status": "new"})
    assert res.status_code == 403


def test_viewer_cannot_update_finding(client, other_headers, viewer_program):
    res = client.patch(f"/programs/{viewer_program}/findings/does-not-exist",
                       json={"title": "x"}, headers=other_headers)
    assert res.status_code == 403


def test_viewer_cannot_suggest_finding(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/findings/any/suggest", {})
    assert res.status_code == 403


def test_viewer_cannot_create_submission(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/submissions",
                {"title": "t", "platform": "HackerOne"})
    assert res.status_code == 403


def test_viewer_cannot_create_schedule(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/schedules",
                {"tool_type": "nuclei", "target_source": "scope", "interval": "daily"})
    assert res.status_code == 403


def test_viewer_cannot_update_scan_status(client, other_headers, viewer_program):
    res = client.patch(f"/programs/{viewer_program}/scans/any", json={"status": "reviewed"},
                       headers=other_headers)
    assert res.status_code == 403


def test_viewer_cannot_bulk_update_scans(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/scans/bulk-status",
                {"ids": ["a"], "status": "reviewed"})
    assert res.status_code == 403


def test_viewer_cannot_import(client, other_headers, viewer_program):
    res = client.post(
        f"/programs/{viewer_program}/imports",
        files={"file": ("nuclei.jsonl", io.BytesIO(b'{"template-id":"x"}'), "application/json")},
        data={"tool_type": "nuclei"},
        headers=other_headers,
    )
    assert res.status_code == 403


def test_viewer_cannot_add_scope(client, other_headers, viewer_program):
    res = _post(client, other_headers, f"/programs/{viewer_program}/scope/in",
                {"value": "example.com", "kind": "domain"})
    assert res.status_code == 403


def test_regular_member_can_write(client, auth_headers, other_headers):
    """Sanity check: a non-viewer 'member' CAN write, so the guard targets viewers only."""
    pid = client.post("/programs", json={"name": "Member Engagement"}, headers=auth_headers).json()["id"]
    client.post(f"/programs/{pid}/members", json={"github_id": "gh_user2", "role": "member"}, headers=auth_headers)
    res = _post(client, other_headers, f"/programs/{pid}/manual-tests", {"title": "member can write"})
    assert res.status_code == 200
    client.delete(f"/programs/{pid}", headers=auth_headers)
