"""Centralized secret redaction for evidence, logs, and API responses.

Evidence is the most dangerous data this platform holds: a captured request that
proves a vulnerability usually also contains the credential used to reach it.
That credential belongs to someone else's production system, and a report is
read by more people than the engagement team.

Redaction happens **on write**, not on render. Storing a raw `Authorization`
header and stripping it in the serializer means one forgotten code path — a log
line, an export, a debug endpoint, an error message — leaks it. What is never
stored cannot leak from a path nobody remembered.

Structure is preserved deliberately. `Authorization: Bearer [REDACTED]` still
proves the request was authenticated, which is often the point of the evidence;
replacing the whole line would destroy the finding it supports.
"""
from __future__ import annotations

import re

PLACEHOLDER = "[REDACTED]"

# Header names whose entire value is a secret.
SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-access-token",
        "x-csrf-token",
        "x-session-token",
        "api-key",
        "auth-token",
        "session",
    }
)

# JSON/form keys whose value is a secret regardless of nesting.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "client_secret",
        "private_key",
        "session_id",
        "sessionid",
        "authorization",
        "credential",
        "credentials",
        "otp",
        "mfa_code",
    }
)

_HEADER_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9\-_]+)\s*:\s*(?P<value>.+)$", re.MULTILINE
)

# key="value" / key: value / key=value in JSON, forms, and query strings.
_KEYED_VALUE = re.compile(
    r"(?P<key>\"?[A-Za-z0-9_\-]+\"?)\s*(?P<sep>[:=])\s*(?P<quote>[\"']?)(?P<value>[^\"'&,}\s]+)(?P=quote)"
)

# Credentials embedded in a URL: scheme://user:pass@host
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<userinfo>[^/\s@]+)@")

# High-entropy bearer-ish tokens that appear without a key name.
_BEARER = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9\-._~+/=]{8,}")

# JWTs are recognisable by shape even when the surrounding key is unknown.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\b")


def _redact_header_line(match: re.Match) -> str:
    name = match.group("name")
    if name.lower() in SENSITIVE_HEADERS:
        return f"{name}: {PLACEHOLDER}"
    return match.group(0)


def _redact_keyed_value(match: re.Match) -> str:
    key = match.group("key").strip('"')
    if key.lower() in SENSITIVE_KEYS:
        quote = match.group("quote")
        return f"{match.group('key')}{match.group('sep')}{quote}{PLACEHOLDER}{quote}"
    return match.group(0)


def redact_text(value: str | None, extra_keys: frozenset[str] | None = None) -> str:
    """Strip secrets from free text — an HTTP exchange, terminal output, a note.

    Order matters. Header lines are handled before generic key/value matching,
    because `Cookie: a=1; b=2` must lose the whole value rather than have each
    pair matched individually and mostly survive.
    """
    if not value:
        return ""

    text = _HEADER_LINE.sub(_redact_header_line, value)

    if extra_keys:
        keys = SENSITIVE_KEYS | {k.lower() for k in extra_keys}

        def _redact_with_extra(match: re.Match) -> str:
            key = match.group("key").strip('"')
            if key.lower() in keys:
                quote = match.group("quote")
                return f"{match.group('key')}{match.group('sep')}{quote}{PLACEHOLDER}{quote}"
            return match.group(0)

        text = _KEYED_VALUE.sub(_redact_with_extra, text)
    else:
        text = _KEYED_VALUE.sub(_redact_keyed_value, text)

    text = _URL_CREDENTIALS.sub(rf"\g<scheme>{PLACEHOLDER}@", text)
    text = _JWT.sub(PLACEHOLDER, text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} {PLACEHOLDER}", text)
    return text


def redact_mapping(data: dict, extra_keys: frozenset[str] | None = None) -> dict:
    """Recursively redact a decoded structure — headers dict, JSON body, params."""
    keys = SENSITIVE_KEYS | ({k.lower() for k in extra_keys} if extra_keys else set())
    header_names = SENSITIVE_HEADERS

    def _walk(node):
        if isinstance(node, dict):
            return {
                k: (
                    PLACEHOLDER
                    if isinstance(k, str) and (k.lower() in keys or k.lower() in header_names)
                    else _walk(v)
                )
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, str):
            return redact_text(node, extra_keys)
        return node

    return _walk(data)


def contains_obvious_secret(value: str | None) -> bool:
    """True when text still looks like it holds a credential.

    Used as a guard in tests and as a last-resort check before evidence is
    returned. Not a substitute for redaction — a detector that misses is
    expected; a redactor that misses is a bug.
    """
    if not value:
        return False
    return bool(_JWT.search(value) or _BEARER.search(value) or _URL_CREDENTIALS.search(value))
