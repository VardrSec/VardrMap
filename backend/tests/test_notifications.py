"""Webhook notifications: helper units + job-failure and nuclei-import triggers."""
import io
import json
import logging
import socket
from unittest.mock import patch

import pytest

from notifications import send_webhook, severity_meets_threshold, validate_webhook_url

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


class TestSendWebhookSSRF:
    """send_webhook resolves the host at send time and refuses any target that
    points at a private/internal address — the layer that defeats a hostname
    (or DNS rebind) aimed at an internal or cloud-metadata IP."""

    @staticmethod
    def _addrinfo(*ips):
        # Mimic socket.getaddrinfo's 5-tuples; the guard reads only sockaddr[0].
        out = []
        for ip in ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((family, socket.SOCK_STREAM, 6, "", (ip, 0)))
        return out

    def test_public_host_is_sent(self):
        with patch("notifications.socket.getaddrinfo", return_value=self._addrinfo("93.184.216.34")), \
             patch("notifications.httpx.post") as mock_post:
            assert send_webhook("https://example.com/h", "hi") is True
            mock_post.assert_called_once()

    def test_host_resolving_to_private_is_blocked(self):
        with patch("notifications.socket.getaddrinfo", return_value=self._addrinfo("10.0.0.5")), \
             patch("notifications.httpx.post") as mock_post:
            assert send_webhook("https://sneaky.example/h", "hi") is False
            mock_post.assert_not_called()

    def test_host_resolving_to_metadata_ip_is_blocked(self):
        with patch("notifications.socket.getaddrinfo", return_value=self._addrinfo("169.254.169.254")), \
             patch("notifications.httpx.post") as mock_post:
            assert send_webhook("https://metadata.example/h", "hi") is False
            mock_post.assert_not_called()

    def test_unresolvable_host_is_blocked(self):
        with patch("notifications.socket.getaddrinfo", side_effect=socket.gaierror), \
             patch("notifications.httpx.post") as mock_post:
            assert send_webhook("https://nope.example/h", "hi") is False
            mock_post.assert_not_called()

    def test_any_private_leg_blocks_mixed_resolution(self):
        # A name resolving to both a public and a private address is refused —
        # the private leg is the SSRF vector.
        with patch("notifications.socket.getaddrinfo",
                   return_value=self._addrinfo("93.184.216.34", "10.0.0.5")), \
             patch("notifications.httpx.post") as mock_post:
            assert send_webhook("https://dual.example/h", "hi") is False
            mock_post.assert_not_called()

    def test_private_ip_literal_blocked_without_dns(self):
        with patch("notifications.socket.getaddrinfo") as mock_resolve, \
             patch("notifications.httpx.post") as mock_post:
            assert send_webhook("https://10.0.0.1/h", "hi") is False
            mock_resolve.assert_not_called()  # literal short-circuits DNS
            mock_post.assert_not_called()

    def test_http_scheme_blocked_before_send(self):
        with patch("notifications.httpx.post") as mock_post:
            assert send_webhook("http://example.com/h", "hi") is False
            mock_post.assert_not_called()

    def test_blocked_host_is_logged(self, caplog):
        """A blocked webhook is no longer a silent swallow — it logs a warning."""
        with patch("notifications.socket.getaddrinfo", return_value=self._addrinfo("10.0.0.5")), \
             patch("notifications.httpx.post"):
            with caplog.at_level(logging.WARNING, logger="vardrmap.notifications"):
                assert send_webhook("https://sneaky.example/h", "hi") is False
        assert any("did not resolve to a public address" in r.message for r in caplog.records)


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
