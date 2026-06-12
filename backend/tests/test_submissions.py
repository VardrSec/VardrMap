"""Submission tracker CRUD and BOLA/IDOR ownership checks."""
from unittest.mock import patch

_SUB = {"title": "XSS in login", "platform": "HackerOne", "status": "submitted", "severity": "high"}


def test_create_submission(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "XSS in login"
    assert data["platform"] == "HackerOne"
    assert data["status"] == "submitted"
    assert "id" in data


def test_list_submissions_empty(client, auth_headers, program_id):
    res = client.get(f"/programs/{program_id}/submissions", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data["submissions"], list)
    assert "total" in data


def test_list_submissions_returns_own(client, auth_headers, program_id):
    client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers)
    res = client.get(f"/programs/{program_id}/submissions", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 1


def test_update_submission_status(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/submissions/{sid}", json={"status": "triaged"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "triaged"


def test_update_submission_payout(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/submissions/{sid}", json={"status": "paid", "payout_usd": 500.0}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["payout_usd"] == 500.0
    assert data["status"] == "paid"
    assert data["resolved_at"] is not None


def test_update_nonexistent_returns_404(client, auth_headers, program_id):
    res = client.patch(f"/programs/{program_id}/submissions/nonexistent", json={"status": "triaged"}, headers=auth_headers)
    assert res.status_code == 404


def test_delete_submission(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/submissions/{sid}", headers=auth_headers)
    assert res.status_code == 200
    ids = [s["id"] for s in client.get(f"/programs/{program_id}/submissions", headers=auth_headers).json()["submissions"]]
    assert sid not in ids


def test_delete_nonexistent_returns_404(client, auth_headers, program_id):
    res = client.delete(f"/programs/{program_id}/submissions/nonexistent", headers=auth_headers)
    assert res.status_code == 404


# BOLA checks

def test_create_in_other_users_program_returns_404(client, other_headers, program_id):
    res = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=other_headers)
    assert res.status_code == 404


def test_list_other_users_program_returns_404(client, other_headers, program_id):
    res = client.get(f"/programs/{program_id}/submissions", headers=other_headers)
    assert res.status_code == 404


def test_update_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    sid = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/submissions/{sid}", json={"status": "triaged"}, headers=other_headers)
    assert res.status_code == 404


def test_delete_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    sid = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/submissions/{sid}", headers=other_headers)
    assert res.status_code == 404


# Audit log checks

def test_create_submission_logs_audit(client, auth_headers, program_id):
    with patch("routers.submissions.log_action") as mock_log:
        res = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers)
    assert res.status_code == 200
    mock_log.assert_called_once()
    assert mock_log.call_args[0][2] == "create"
    assert mock_log.call_args[0][3] == "submission"


def test_update_submission_logs_audit(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers).json()["id"]
    with patch("routers.submissions.log_action") as mock_log:
        res = client.patch(f"/programs/{program_id}/submissions/{sid}", json={"status": "triaged"}, headers=auth_headers)
    assert res.status_code == 200
    mock_log.assert_called_once()
    assert mock_log.call_args[0][2] == "update"
    assert mock_log.call_args[0][3] == "submission"


def test_delete_submission_logs_audit(client, auth_headers, program_id):
    sid = client.post(f"/programs/{program_id}/submissions", json=_SUB, headers=auth_headers).json()["id"]
    with patch("routers.submissions.log_action") as mock_log:
        res = client.delete(f"/programs/{program_id}/submissions/{sid}", headers=auth_headers)
    assert res.status_code == 200
    mock_log.assert_called_once()
    assert mock_log.call_args[0][2] == "delete"
    assert mock_log.call_args[0][3] == "submission"


# Auth checks

def test_list_unauthorized(client, program_id):
    res = client.get(f"/programs/{program_id}/submissions")
    assert res.status_code == 401


def test_create_unauthorized(client, program_id):
    res = client.post(f"/programs/{program_id}/submissions", json=_SUB)
    assert res.status_code == 401
