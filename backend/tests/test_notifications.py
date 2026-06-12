"""Webhook notifications: helper units + job-failure and nuclei-import triggers."""
import io
import json
from unittest.mock import patch

import pytest

from notifications import severity_meets_threshold, validate_webhook_url

_WEBHOOK = "https://discord.com/api/webhooks/123/abc"


@pytest.fixture
def webhook_user(client, auth_headers):
    """Set a webhook for user1 and ALWAYS clear it after — a leftover URL would
    make unrelated tests fire real HTTP from background tasks."""
    client.patch("/settings", json={"webhook_url": _WEBHOOK, "notify_min_severity": "high"}, headers=auth_headers)
    yield
    client.patch("/settings", json={"webhook_url": ""}, headers=auth_headers)


def _make_job(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/jobs",
                      json={"tool_type": "httpx", "target_source": "scope"}, headers=auth_headers)
    return res.json()["id"]


# ---------------------------------------------------------------------------
# Helper units
# ---------------------------------------------------------------------------

class TestSeverityThreshold:
    def test_at_threshold_matches(self):
        assert severity_meets_threshold("high", "high") is True

    def test_above_threshold_matches(self):
        assert severity_meets_threshold("critical", "high") is True

    def test_below_threshold_does_not_match(self):
        assert severity_meets_threshold("medium", "high") is False

    def test_unknown_severity_never_matches(self):
        assert severity_meets_threshold("unknown", "info") is False
        assert severity_meets_threshold("high", "unknown") is False

    def test_case_insensitive(self):
        assert severity_meets_threshold("CRITICAL", "High") is True


class TestValidateWebhookUrl:
    def test_valid_https_passes(self):
        assert validate_webhook_url(_WEBHOOK) is None

    def test_http_rejected(self):
        assert validate_webhook_url("http://example.com/h") is not None

    def test_loopback_rejected(self):
        assert validate_webhook_url("https://127.0.0.1/h") is not None

    def test_private_ip_rejected(self):
        assert validate_webhook_url("https://10.1.2.3/h") is not None

    def test_link_local_rejected(self):
        assert validate_webhook_url("https://169.254.169.254/h") is not None

    def test_localhost_rejected(self):
        assert validate_webhook_url("https://localhost/h") is not None


# ---------------------------------------------------------------------------
# Job failure notifications
# ---------------------------------------------------------------------------

def test_failed_job_fires_webhook(client, auth_headers, program_id, webhook_user):
    job_id = _make_job(client, auth_headers, program_id)
    with patch("routers.jobs.send_webhook") as mock_send:
        res = client.patch(f"/jobs/{job_id}",
                           json={"status": "failed", "error_message": "tool crashed"},
                           headers=auth_headers)
    assert res.status_code == 200
    mock_send.assert_called_once()
    url, message = mock_send.call_args[0]
    assert url == _WEBHOOK
    assert "httpx" in message
    assert "tool crashed" in message


def test_cancelled_job_does_not_fire_webhook(client, auth_headers, program_id, webhook_user):
    """Operator-initiated cancels are not failures worth pinging about."""
    job_id = _make_job(client, auth_headers, program_id)
    with patch("routers.jobs.send_webhook") as mock_send:
        client.patch(f"/jobs/{job_id}",
                     json={"status": "failed", "error_message": "cancelled by operator"},
                     headers=auth_headers)
    mock_send.assert_not_called()


def test_failed_job_without_webhook_does_not_fire(client, auth_headers, program_id):
    job_id = _make_job(client, auth_headers, program_id)
    with patch("routers.jobs.send_webhook") as mock_send:
        client.patch(f"/jobs/{job_id}",
                     json={"status": "failed", "error_message": "boom"},
                     headers=auth_headers)
    mock_send.assert_not_called()


def test_done_job_does_not_fire_webhook(client, auth_headers, program_id, webhook_user):
    job_id = _make_job(client, auth_headers, program_id)
    with patch("routers.jobs.send_webhook") as mock_send:
        client.patch(f"/jobs/{job_id}", json={"status": "done"}, headers=auth_headers)
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Nuclei import notifications
# ---------------------------------------------------------------------------

def _upload_nuclei(client, auth_headers, program_id, items):
    return client.post(
        f"/programs/{program_id}/imports",
        data={"tool_type": "nuclei"},
        files={"file": ("nuclei.json", io.BytesIO(json.dumps(items).encode()), "application/json")},
        headers=auth_headers,
    )


def _nuclei_item(severity, name="Test Finding"):
    return {
        "template-id": f"tpl-{severity}",
        "info": {"name": name, "severity": severity, "description": "d"},
        "matched-at": "https://example.com/x",
        "type": "http",
    }


def test_notable_import_fires_webhook(client, auth_headers, program_id, webhook_user):
    with patch("routers.imports.send_webhook") as mock_send:
        res = _upload_nuclei(client, auth_headers, program_id,
                             [_nuclei_item("critical", "RCE in login"), _nuclei_item("info")])
    assert res.status_code == 200
    mock_send.assert_called_once()
    url, message = mock_send.call_args[0]
    assert url == _WEBHOOK
    assert "1 high+" in message
    assert "RCE in login" in message


def test_below_threshold_import_does_not_fire(client, auth_headers, program_id, webhook_user):
    with patch("routers.imports.send_webhook") as mock_send:
        res = _upload_nuclei(client, auth_headers, program_id,
                             [_nuclei_item("low"), _nuclei_item("medium")])
    assert res.status_code == 200
    mock_send.assert_not_called()


def test_import_without_webhook_does_not_fire(client, auth_headers, program_id):
    with patch("routers.imports.send_webhook") as mock_send:
        res = _upload_nuclei(client, auth_headers, program_id, [_nuclei_item("critical")])
    assert res.status_code == 200
    mock_send.assert_not_called()
