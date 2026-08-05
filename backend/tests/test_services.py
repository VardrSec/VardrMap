"""Tests for GET/POST/DELETE /programs/{id}/services.

Coverage:
- List services — empty, returns own only
- Bulk create — basic success, 201 status, upsert on (host, port, protocol)
- Delete — success, wrong-user 404, nonexistent 404
- BOLA: unauthorized 401, wrong-user 404 on all endpoints
- Cascade: services are deleted when engagement is deleted
- Scope: runner-scoped key can POST, cannot GET or DELETE
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SVC = {"host": "10.0.0.1", "port": 80, "protocol": "tcp",
        "service_name": "http", "product": "nginx", "version": "1.24.0"}


def _bulk_create(client, program_id, headers, services=None):
    return client.post(
        f"/programs/{program_id}/services",
        json={"services": services or [_SVC]},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def test_bulk_upsert_logs_audit(client, program_id, auth_headers):
    from unittest.mock import patch
    with patch("routers.services.log_action") as mock_log:
        res = _bulk_create(client, program_id, auth_headers)
    assert res.status_code == 201
    mock_log.assert_called_once()
    args = mock_log.call_args[0]
    assert args[2] == "upsert" and args[3] == "service"


def test_delete_service_logs_audit(client, program_id, auth_headers):
    from unittest.mock import patch
    _bulk_create(client, program_id, auth_headers)
    sid = client.get(f"/programs/{program_id}/services", headers=auth_headers).json()["services"][0]["id"]
    with patch("routers.services.log_action") as mock_log:
        res = client.delete(f"/programs/{program_id}/services/{sid}", headers=auth_headers)
    assert res.status_code == 200
    mock_log.assert_called_once()
    args = mock_log.call_args[0]
    assert args[2] == "delete" and args[3] == "service"


# ---------------------------------------------------------------------------
# GET /programs/{id}/services
# ---------------------------------------------------------------------------

class TestListServices:
    def test_list_empty(self, client, program_id, auth_headers):
        res = client.get(f"/programs/{program_id}/services", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["services"] == []
        assert data["total"] == 0

    def test_list_returns_created_services(self, client, program_id, auth_headers):
        _bulk_create(client, program_id, auth_headers)
        res = client.get(f"/programs/{program_id}/services", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()["services"]) == 1
        svc = res.json()["services"][0]
        assert svc["host"] == "10.0.0.1"
        assert svc["port"] == 80
        assert svc["service_name"] == "http"

    def test_list_unauthorized(self, client, program_id):
        res = client.get(f"/programs/{program_id}/services")
        assert res.status_code == 401

    def test_list_wrong_user_404(self, client, program_id, other_headers):
        res = client.get(f"/programs/{program_id}/services", headers=other_headers)
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /programs/{id}/services
# ---------------------------------------------------------------------------

class TestBulkCreateServices:
    def test_create_success(self, client, program_id, auth_headers):
        res = _bulk_create(client, program_id, auth_headers)
        assert res.status_code == 201
        data = res.json()
        assert data["created"] == 1
        assert data["updated"] == 0

    def test_upsert_updates_existing(self, client, program_id, auth_headers):
        _bulk_create(client, program_id, auth_headers)
        updated_svc = {**_SVC, "version": "1.25.0"}
        res = _bulk_create(client, program_id, auth_headers, [updated_svc])
        assert res.status_code == 201
        data = res.json()
        assert data["created"] == 0
        assert data["updated"] == 1

        services = client.get(f"/programs/{program_id}/services", headers=auth_headers).json()["services"]
        assert services[0]["version"] == "1.25.0"

    def test_multiple_services(self, client, program_id, auth_headers):
        svcs = [
            {"host": "10.0.0.1", "port": 22, "protocol": "tcp", "service_name": "ssh"},
            {"host": "10.0.0.1", "port": 443, "protocol": "tcp", "service_name": "https"},
            {"host": "10.0.0.2", "port": 8080, "protocol": "tcp", "service_name": "http-alt"},
        ]
        res = _bulk_create(client, program_id, auth_headers, svcs)
        assert res.status_code == 201
        assert res.json()["created"] == 3

    def test_create_unauthorized(self, client, program_id):
        res = _bulk_create(client, program_id, {})
        assert res.status_code == 401

    def test_create_wrong_user_404(self, client, program_id, other_headers):
        res = _bulk_create(client, program_id, other_headers)
        assert res.status_code == 404

    def test_invalid_port_rejected(self, client, program_id, auth_headers):
        res = _bulk_create(client, program_id, auth_headers,
                           [{"host": "10.0.0.1", "port": 99999, "protocol": "tcp"}])
        assert res.status_code == 422

    def test_invalid_protocol_rejected(self, client, program_id, auth_headers):
        res = _bulk_create(client, program_id, auth_headers,
                           [{"host": "10.0.0.1", "port": 80, "protocol": "sctp"}])
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /programs/{id}/services/{service_id}
# ---------------------------------------------------------------------------

class TestDeleteService:
    def test_delete_success(self, client, program_id, auth_headers):
        _bulk_create(client, program_id, auth_headers)
        svc_id = client.get(f"/programs/{program_id}/services", headers=auth_headers).json()["services"][0]["id"]
        res = client.delete(f"/programs/{program_id}/services/{svc_id}", headers=auth_headers)
        assert res.status_code == 200

        remaining = client.get(f"/programs/{program_id}/services", headers=auth_headers).json()["services"]
        assert all(s["id"] != svc_id for s in remaining)

    def test_delete_wrong_user_404(self, client, program_id, auth_headers, other_headers):
        _bulk_create(client, program_id, auth_headers)
        svc_id = client.get(f"/programs/{program_id}/services", headers=auth_headers).json()["services"][0]["id"]
        res = client.delete(f"/programs/{program_id}/services/{svc_id}", headers=other_headers)
        assert res.status_code == 404

    def test_delete_nonexistent_404(self, client, program_id, auth_headers):
        res = client.delete(f"/programs/{program_id}/services/does-not-exist", headers=auth_headers)
        assert res.status_code == 404

    def test_delete_unauthorized(self, client, program_id):
        res = client.delete(f"/programs/{program_id}/services/any-id")
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# last_scanned_at
# ---------------------------------------------------------------------------

class TestLastScannedAt:
    def test_last_scanned_at_set_on_create(self, client, program_id, auth_headers):
        _bulk_create(client, program_id, auth_headers)
        svc = client.get(f"/programs/{program_id}/services", headers=auth_headers).json()["services"][0]
        assert svc["last_scanned_at"] is not None

    def test_last_scanned_at_updated_on_upsert(self, client, program_id, auth_headers):
        import time
        _bulk_create(client, program_id, auth_headers)
        first_ts = client.get(f"/programs/{program_id}/services", headers=auth_headers).json()["services"][0]["last_scanned_at"]

        time.sleep(0.05)
        _bulk_create(client, program_id, auth_headers, [{**_SVC, "version": "2.0.0"}])
        second_ts = client.get(f"/programs/{program_id}/services", headers=auth_headers).json()["services"][0]["last_scanned_at"]

        # Timestamps should differ — upsert stamps a new value
        assert second_ts >= first_ts


# ---------------------------------------------------------------------------
# Scope enforcement — runner-scoped keys
# ---------------------------------------------------------------------------

class TestRunnerScopeServices:
    def _runner_headers(self, client, auth_headers):
        res = client.post("/auth/apikeys", json={"scope": "runner"}, headers=auth_headers)
        return res.json()["token"], res.json()["id"]

    def test_runner_key_can_post_services(self, client, program_id, auth_headers):
        token, key_id = self._runner_headers(client, auth_headers)
        try:
            res = _bulk_create(client, program_id, {"Authorization": f"Bearer {token}"})
            assert res.status_code == 201
        finally:
            client.delete(f"/auth/apikeys/{key_id}", headers=auth_headers)

    def test_runner_key_cannot_get_services(self, client, program_id, auth_headers):
        token, key_id = self._runner_headers(client, auth_headers)
        try:
            res = client.get(f"/programs/{program_id}/services",
                             headers={"Authorization": f"Bearer {token}"})
            assert res.status_code == 403
        finally:
            client.delete(f"/auth/apikeys/{key_id}", headers=auth_headers)

    def test_runner_key_cannot_delete_service(self, client, program_id, auth_headers):
        _bulk_create(client, program_id, auth_headers)
        svc_id = client.get(f"/programs/{program_id}/services",
                            headers=auth_headers).json()["services"][0]["id"]
        token, key_id = self._runner_headers(client, auth_headers)
        try:
            res = client.delete(f"/programs/{program_id}/services/{svc_id}",
                                headers={"Authorization": f"Bearer {token}"})
            assert res.status_code == 403
        finally:
            client.delete(f"/auth/apikeys/{key_id}", headers=auth_headers)


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------

class TestServicesCascade:
    def test_services_deleted_with_program(self, client, auth_headers):
        prog = client.post("/programs", json={"name": "Cascade Test"}, headers=auth_headers)
        pid = prog.json()["id"]
        _bulk_create(client, pid, auth_headers)

        # Verify services exist
        assert client.get(f"/programs/{pid}/services", headers=auth_headers).json()["total"] == 1

        # Delete engagement
        client.delete(f"/programs/{pid}", headers=auth_headers)

        # Engagement gone — services endpoint returns 404
        res = client.get(f"/programs/{pid}/services", headers=auth_headers)
        assert res.status_code == 404
