"""Tests for POST /runner/heartbeat and GET /runner/status.

Coverage:
- POST creates a heartbeat row and returns {ok, last_seen}
- POST upserts (second call updates the same row)
- GET returns online=false + null fields if no heartbeat exists
- GET returns online=true and real fields after a recent heartbeat
- BOLA: user2 gets their own (empty) status even when user1 has a heartbeat
- Unauthorized → 401 on both endpoints
"""

import pytest


_PAYLOAD = {
    "hostname": "dev-laptop",
    "version":  "0.1.0",
    "os":       "Linux 6.5",
    "tools": {
        "httpx":     {"ok": True,  "version": "v1.6.9"},
        "nuclei":    {"ok": True,  "version": "v3.2.0"},
        "subfinder": {"ok": False, "version": None},
    },
}


# ---------------------------------------------------------------------------
# POST /runner/heartbeat
# ---------------------------------------------------------------------------

class TestPostHeartbeat:
    def test_creates_heartbeat(self, client, auth_headers):
        res = client.post("/runner/heartbeat", json=_PAYLOAD, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["last_seen"] is not None

    def test_upserts_on_second_call(self, client, auth_headers):
        client.post("/runner/heartbeat", json=_PAYLOAD, headers=auth_headers)
        updated = {**_PAYLOAD, "hostname": "new-hostname"}
        res = client.post("/runner/heartbeat", json=updated, headers=auth_headers)
        assert res.status_code == 200
        # Status endpoint should reflect updated hostname
        status = client.get("/runner/status", headers=auth_headers).json()
        assert status["hostname"] == "new-hostname"

    def test_unauthorized(self, client):
        res = client.post("/runner/heartbeat", json=_PAYLOAD)
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# GET /runner/status
# ---------------------------------------------------------------------------

class TestGetRunnerStatus:
    def test_no_heartbeat_returns_offline(self, client, other_headers):
        # user2 has never sent a heartbeat
        res = client.get("/runner/status", headers=other_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["online"] is False
        assert data["last_seen"] is None
        assert data["tools"] == {}

    def test_recent_heartbeat_returns_online(self, client, auth_headers):
        client.post("/runner/heartbeat", json=_PAYLOAD, headers=auth_headers)
        res = client.get("/runner/status", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["online"] is True
        assert data["hostname"] == _PAYLOAD["hostname"]
        assert data["version"]  == _PAYLOAD["version"]
        assert data["os"]       == _PAYLOAD["os"]
        assert data["tools"]["httpx"]["ok"] is True
        assert data["tools"]["subfinder"]["ok"] is False

    def test_bola_user2_sees_own_empty_status(self, client, auth_headers, other_headers):
        # user1 sends heartbeat; user2 should still get their own (empty) status
        client.post("/runner/heartbeat", json=_PAYLOAD, headers=auth_headers)
        res = client.get("/runner/status", headers=other_headers)
        assert res.status_code == 200
        data = res.json()
        # user2 has no heartbeat; must not see user1's data
        assert data["online"] is False
        assert data["hostname"] is None

    def test_unauthorized(self, client):
        res = client.get("/runner/status")
        assert res.status_code == 401
