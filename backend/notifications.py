"""
Outbound webhook notifications.

Users configure a Discord/Slack-style incoming webhook URL in Settings.
The payload includes both "content" (Discord) and "text" (Slack) keys so
either platform accepts it without per-platform configuration.

Delivery is best-effort: send_webhook never raises, and callers dispatch it
via FastAPI BackgroundTasks so a slow webhook never delays an API response.

SSRF model: the backend itself makes the outbound POST, so a webhook URL is an
attacker-controlled request target. Two layers guard it:

  1. validate_webhook_url() — a cheap, no-network check run when the URL is
     saved. Requires HTTPS and rejects loopback/private/link-local *IP literals*
     and obvious local names. Gives immediate feedback on bad input.

  2. send_webhook() — re-validates and then *resolves the host and blocks any
     private/loopback/link-local/reserved address* immediately before sending.
     This is the authoritative guard: it runs at request time, so it also
     catches DNS names that resolve (or have been re-pointed via rebinding) to
     internal addresses such as cloud-metadata endpoints. A blocked or
     unresolvable host means the request is never made.
"""
import ipaddress
import socket
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


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address the backend must never be coerced into contacting:
    private ranges, loopback, link-local (incl. the 169.254.169.254 metadata
    address), reserved, multicast, and the unspecified address."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_webhook_url(url: str) -> Optional[str]:
    """Return an error message if the URL is not a safe webhook target, else None.

    Fast, no-network pre-check used when a webhook URL is saved. Requires HTTPS
    and rejects local names and private/loopback/link-local IP literals. DNS
    names that resolve to private ranges are intentionally *not* caught here —
    that check is enforced authoritatively at send time by send_webhook(), so it
    cannot be bypassed by DNS rebinding.
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
        if _is_blocked_ip(ipaddress.ip_address(host)):
            return "webhook_url must not point to a private address"
    except ValueError:
        pass  # hostname, not an IP literal — resolution is checked at send time
    return None


def _host_resolves_safely(host: str) -> bool:
    """True only if `host` resolves to at least one address and *every* resolved
    address is public. Resolution failure, or any private/loopback/link-local/
    reserved address, returns False so the webhook is not sent.

    Resolving here — at send time — is what makes the guard rebinding-resistant:
    a name that passed validation can still be blocked if it now points inward.
    """
    if not host:
        return False
    # An IP literal never needs DNS; check it directly so an alternate textual
    # form that slipped past validate_webhook_url is still caught.
    try:
        return not _is_blocked_ip(ipaddress.ip_address(host))
    except ValueError:
        pass  # not a literal — fall through to DNS resolution
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for address in addresses:
        try:
            if _is_blocked_ip(ipaddress.ip_address(address)):
                return False
        except ValueError:
            return False  # unparseable resolved address — fail closed
    return True


def send_webhook(url: str, message: str) -> bool:
    """POST a notification message. Never raises — returns False on any failure
    or if the SSRF guard rejects the target.

    The guard runs again here (not only at config time) because this is where the
    outbound request is actually made: re-validating and re-resolving immediately
    before sending blocks names that point — or have been re-pointed — at private
    or metadata addresses.
    """
    if validate_webhook_url(url) is not None:
        return False
    host = urllib.parse.urlparse(url).hostname or ""
    if not _host_resolves_safely(host):
        return False
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
