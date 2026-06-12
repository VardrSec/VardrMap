"""User settings: webhook URL validation (SSRF guard), severity threshold, auth."""
import pytest

_GOOD_URL = "https://discord.com/api/webhooks/123/abc"


@pytest.fixture
def clear_webhook(client, auth_headers):
    """Reset webhook settings after the test — the shared test DB persists rows,
    and a leftover webhook_url would make later job-failure tests fire real HTTP."""
    yield
    client.patch("/settings", json={"webhook_url": "", "notify_min_severity": "high"}, headers=auth_headers)


def test_get_settings_returns_defaults(client, other_headers):
    res = client.get("/settings", headers=other_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["webhook_url"] == ""
    assert data["notify_min_severity"] == "high"


def test_patch_webhook_url(client, auth_headers, clear_webhook):
    res = client.patch("/settings", json={"webhook_url": _GOOD_URL}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["webhook_url"] == _GOOD_URL
    # persists
    assert client.get("/settings", headers=auth_headers).json()["webhook_url"] == _GOOD_URL


def test_patch_severity_threshold(client, auth_headers, clear_webhook):
    res = client.patch("/settings", json={"notify_min_severity": "critical"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["notify_min_severity"] == "critical"


def test_clear_webhook_with_empty_string(client, auth_headers, clear_webhook):
    client.patch("/settings", json={"webhook_url": _GOOD_URL}, headers=auth_headers)
    res = client.patch("/settings", json={"webhook_url": ""}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["webhook_url"] == ""


def test_invalid_severity_rejected(client, auth_headers):
    res = client.patch("/settings", json={"notify_min_severity": "catastrophic"}, headers=auth_headers)
    assert res.status_code == 400


# SSRF guard — backend POSTs to this URL, so reject anything pointing inward

@pytest.mark.parametrize("bad_url", [
    "http://discord.com/api/webhooks/123/abc",   # not https
    "https://localhost/hook",
    "https://sub.localhost/hook",
    "https://127.0.0.1/hook",
    "https://10.0.0.5/hook",
    "https://192.168.1.1/hook",
    "https://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
    "https://backend.internal/hook",
    "ftp://example.com/hook",
    "https://",
])
def test_unsafe_webhook_url_rejected(client, auth_headers, bad_url):
    res = client.patch("/settings", json={"webhook_url": bad_url}, headers=auth_headers)
    assert res.status_code == 400


def test_settings_are_per_user(client, auth_headers, other_headers, clear_webhook):
    client.patch("/settings", json={"webhook_url": _GOOD_URL}, headers=auth_headers)
    res = client.get("/settings", headers=other_headers)
    assert res.json()["webhook_url"] == ""  # user2 must not see user1's webhook


def test_get_unauthorized(client):
    assert client.get("/settings").status_code == 401


def test_patch_unauthorized(client):
    assert client.patch("/settings", json={"webhook_url": _GOOD_URL}).status_code == 401
