"""Webhook delivery pins the approved address without losing TLS identity."""
from unittest.mock import patch

import httpx
import pytest
from notifications import _post_to_address, send_webhook, validate_webhook_url


@pytest.mark.parametrize("url", ["https://[broken/h", "https://example.com:bad/h", "https://user:secret@example.com/h", "https://example.com/h\n", "https://100.64.0.1/h"])
def test_malformed_webhook_urls_are_rejected(url):
    assert validate_webhook_url(url) is not None


def test_transport_pins_ip_preserves_hostname_and_checks_status():
    with patch("notifications.httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        _post_to_address("https://hooks.example:8443/private-hook", "93.184.216.34", "hello")
        factory.assert_called_once_with(trust_env=False)
        args, kwargs = client.post.call_args
        assert args[0].host == "93.184.216.34"
        assert args[0].port == 8443
        assert kwargs["headers"]["Host"] == "hooks.example:8443"
        assert kwargs["extensions"]["sni_hostname"] == "hooks.example"
        assert kwargs["follow_redirects"] is False
        client.post.return_value.raise_for_status.assert_called_once()


def test_rebinding_cannot_trigger_a_second_hostname_resolution():
    public = [(2, 1, 6, "", ("93.184.216.34", 443))]
    private = [(2, 1, 6, "", ("127.0.0.1", 443))]
    with patch("notifications.socket.getaddrinfo", side_effect=[public, private]) as dns, patch("notifications._post_to_address") as post:
        assert send_webhook("https://hooks.example/h", "hello")
        assert dns.call_count == 1
        post.assert_called_once_with("https://hooks.example/h", "93.184.216.34", "hello")


def test_delivery_errors_do_not_log_webhook_secret(caplog):
    secret_url = "https://93.184.216.34/private-webhook-secret"
    with patch("notifications._post_to_address", side_effect=httpx.ConnectError(secret_url)):
        assert not send_webhook(secret_url, "hello")
    assert "private-webhook-secret" not in caplog.text
