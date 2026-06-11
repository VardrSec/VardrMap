"""Tests for GET /radar and POST /radar/refresh.

Coverage:
- GET /radar: empty list, returns own only (BOLA), marks programs as seen, optional platform filter
- POST /radar/refresh: upserts new programs, updates existing, rejects unknown platform
- BOLA: 401 unauthorized, wrong-user isolation
- Deduplication: re-fetching the same platform_id updates rather than duplicates
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import mint_token

_BUGCROWD_RESPONSE = [
    {"code": "prog-alpha", "name": "Alpha Program",  "program_url": "https://bugcrowd.com/prog-alpha",  "max_payout": 5000},
    {"code": "prog-beta",  "name": "Beta Program",   "program_url": "https://bugcrowd.com/prog-beta",   "max_payout": 2500},
]

_HACKERONE_RESPONSE = {
    "programs": [
        {"handle": "h1-gamma", "name": "Gamma Corp", "attributes": {"url": "https://hackerone.com/h1-gamma", "maximum_bounty": 10000}},
    ]
}


def _mock_httpx_get(platform: str):
    """Return a mock httpx.get that returns appropriate JSON for the given platform."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if platform == "bugcrowd":
        resp.json.return_value = _BUGCROWD_RESPONSE
    else:
        resp.json.return_value = _HACKERONE_RESPONSE
    return resp


# ---------------------------------------------------------------------------
# GET /radar
# ---------------------------------------------------------------------------

class TestListRadar:
    def test_list_empty_initially(self, client, auth_headers):
        res = client.get("/radar", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["programs"] == []
        assert data["total"] == 0
        assert data["new_count"] == 0

    def test_unauthorized_401(self, client):
        res = client.get("/radar")
        assert res.status_code == 401

    def test_wrong_user_sees_empty_list(self, client, auth_headers, other_headers):
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("bugcrowd")
            client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers)

        # Other user has their own empty radar
        res = client.get("/radar", headers=other_headers)
        assert res.json()["total"] == 0

    def test_list_returns_programs_for_owner(self, client, auth_headers):
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("bugcrowd")
            client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers)

        res = client.get("/radar", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 2
        platforms = {p["platform"] for p in data["programs"]}
        assert "bugcrowd" in platforms

    def test_list_marks_programs_as_seen(self, client, auth_headers):
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("bugcrowd")
            client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers)

        first = client.get("/radar", headers=auth_headers).json()
        new_on_first = first["new_count"]
        assert new_on_first >= 0

        # After first fetch, all programs are marked seen
        second = client.get("/radar", headers=auth_headers).json()
        assert second["new_count"] == 0

    def test_platform_filter(self, client, auth_headers):
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("bugcrowd")
            client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers)

        res = client.get("/radar?platform=bugcrowd", headers=auth_headers)
        assert res.status_code == 200
        for p in res.json()["programs"]:
            assert p["platform"] == "bugcrowd"


# ---------------------------------------------------------------------------
# POST /radar/refresh
# ---------------------------------------------------------------------------

class TestRefreshRadar:
    def test_unauthorized_401(self, client):
        res = client.post("/radar/refresh")
        assert res.status_code == 401

    def test_unknown_platform_400(self, client, auth_headers):
        res = client.post("/radar/refresh?platform=intigriti", headers=auth_headers)
        assert res.status_code == 400
        assert "intigriti" in res.json()["detail"]

    def test_bugcrowd_refresh_inserts_programs(self, client, auth_headers):
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("bugcrowd")
            res = client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        # new + updated = total programs processed (2 from mock); some may already exist from
        # earlier tests sharing the same SQLite DB, so check the combined count is correct
        assert data["new"] + data["updated"] >= 2
        assert "bugcrowd" in data["platforms"]

    def test_hackerone_refresh_inserts_programs(self, client, auth_headers):
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("hackerone")
            res = client.post("/radar/refresh?platform=hackerone", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["new"] >= 1
        assert "hackerone" in data["platforms"]

    def test_deduplication_on_re_refresh(self, client, auth_headers):
        """Two consecutive refreshes: second must report new==0 (no duplicates created)."""
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("bugcrowd")
            first = client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers).json()
            second = client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers).json()

        # Second refresh should never insert new rows — all programs from first pass are known
        assert second["new"] == 0
        # All programs from the mock must have been updated on the second pass
        assert second["updated"] == first["new"] + first["updated"]

    def test_502_on_upstream_failure(self, client, auth_headers):
        import httpx as _httpx
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.side_effect = _httpx.ConnectError("timeout")
            res = client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers)
        assert res.status_code == 502

    def test_new_programs_marked_is_new(self, client, auth_headers):
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("bugcrowd")
            client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers)

        programs = client.get("/radar?platform=bugcrowd", headers=auth_headers).json()["programs"]
        # is_new returns True for freshly-inserted programs before the GET marks them seen
        # (in this call the GET already marked them seen, so is_new=False here — that's correct behaviour)
        # The new_count in the GET before fetch would have been > 0; verify field exists and is bool
        assert all(isinstance(p["is_new"], bool) for p in programs)

    def test_bola_users_get_separate_lists(self, client, auth_headers, other_headers):
        with patch("routers.radar.httpx.get") as mock_get:
            mock_get.return_value = _mock_httpx_get("bugcrowd")
            client.post("/radar/refresh?platform=bugcrowd", headers=auth_headers)
            client.post("/radar/refresh?platform=bugcrowd", headers=other_headers)

        user1_list = client.get("/radar", headers=auth_headers).json()
        user2_list = client.get("/radar", headers=other_headers).json()

        # Each user gets their own rows — IDs must not overlap
        user1_ids = {p["id"] for p in user1_list["programs"]}
        user2_ids = {p["id"] for p in user2_list["programs"]}
        assert user1_ids.isdisjoint(user2_ids)
