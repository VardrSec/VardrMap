"""
Outbound webhook notifications.

Users configure a Discord/Slack-style incoming webhook URL in Settings.
The payload includes both "content" (Discord) and "text" (Slack) keys so
either platform accepts it without per-platform configuration.

Delivery is best-effort: send_webhook never raises, and callers dispatch it
via FastAPI BackgroundTasks so a slow webhook never delays an API response.
"""
import ipaddress
import urllib.parse
from typing import Optional

import httpx

_WEBHOOK_TIMEOUT = 5  # seconds

# Severity ordering for threshold comparison
_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
VALID_SEVERITIES = set(_SEVERITY_ORDER)


def severity_meets_threshold(severity: str, minimum: str) -> bool:
    """True if `severity` is at or above `minimum`. Unknown severities never match."""
    sev = _SEVERITY_ORDER.get((severity or "").lower())
    floor = _SEVERITY_ORDER.get((minimum or "").lower())
    if sev is None or floor is None:
        return False
    return sev >= floor


def validate_webhook_url(url: str) -> Optional[str]:
    """Return an error message if the URL is not a safe webhook target, else None.

    SSRF guard: the backend POSTs to this user-supplied URL, so require HTTPS
    and reject loopback/private/link-local IP literals and localhost. DNS names
    that resolve to private ranges are not caught — acceptable for a
    personal-use tool where users configure their own webhooks.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        return "webhook_url must use https"
    host = parsed.hostname or ""
    if not host:
        return "webhook_url must include a hostname"
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
        return "webhook_url must not point to a local address"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return "webhook_url must not point to a private address"
    except ValueError:
        pass  # hostname, not an IP literal
    return None


def send_webhook(url: str, message: str) -> bool:
    """POST a notification message. Never raises — returns False on any failure."""
    try:
        httpx.post(
            url,
            json={"content": message, "text": message},
            timeout=_WEBHOOK_TIMEOUT,
            follow_redirects=False,
        )
        return True
    except Exception:
        return False
