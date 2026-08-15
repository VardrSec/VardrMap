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
#
# Two patterns rather than one. A *quoted* value runs to its closing quote and
# may contain anything — spaces, commas, punctuation. An earlier single pattern
# excluded those characters from the value class, so `{"password": "hunter 2"}`
# and `{"api_key": "sk_live_abcd,efgh"}` were stored verbatim: the match ended
# at the space or comma and the redaction never fired. Passphrases contain
# spaces and keys contain punctuation, so those were ordinary secrets, not
# exotic ones.
_KEYED_QUOTED = re.compile(
    r"(?P<key>\"?[A-Za-z0-9_\-]+\"?)\s*(?P<sep>[:=])\s*(?P<quote>[\"'])(?P<value>(?:[^\"'\\]|\\.)*)(?P=quote)"
)

# Unquoted values run to a structural delimiter or end of line. The value must
# not *start* with a quote — that case belongs to _KEYED_QUOTED, which runs
# first, and matching it here again would chew through the placeholder it just
# inserted and corrupt the surrounding JSON. Spaces are
# deliberately *inside* the value: `password: my long passphrase` is one secret,
# and stopping at the first space would leak all but the first word. Redacting a
# few trailing words of prose is a cost worth paying against that.
_KEYED_BARE = re.compile(
    r"(?P<key>\"?[A-Za-z0-9_\-]+\"?)\s*(?P<sep>[:=])\s*"
    r"(?P<value>[^\"'\s&;,}\]\r\n][^&;,}\]\r\n]*)"
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


def _sub_quoted(keys: frozenset[str]):
    def _apply(match: re.Match) -> str:
        if match.group("key").strip("\"'").lower() in keys:
            quote = match.group("quote")
            return f"{match.group('key')}{match.group('sep')}{quote}{PLACEHOLDER}{quote}"
        return match.group(0)

    return _apply


def _sub_bare(keys: frozenset[str]):
    def _apply(match: re.Match) -> str:
        if match.group("key").strip("\"'").lower() in keys:
            return f"{match.group('key')}{match.group('sep')}{PLACEHOLDER}"
        return match.group(0)

    return _apply


def redact_text(value: str | None, extra_keys: frozenset[str] | None = None) -> str:
    """Strip secrets from free text — an HTTP exchange, terminal output, a note.

    Order matters. Header lines are handled before generic key/value matching,
    because `Cookie: a=1; b=2` must lose the whole value rather than have each
    pair matched individually and mostly survive.
    """
    if not value:
        return ""

    text = _HEADER_LINE.sub(_redact_header_line, value)

    keys = SENSITIVE_KEYS | ({k.lower() for k in extra_keys} if extra_keys else set())
    # Quoted first: a quoted value owns everything up to its closing quote, so
    # matching it before the bare pattern keeps spaces and commas inside the
    # secret rather than letting the value end early.
    text = _KEYED_QUOTED.sub(_sub_quoted(keys), text)
    text = _KEYED_BARE.sub(_sub_bare(keys), text)

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
