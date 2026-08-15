"""Secret redaction.

Every test here is a leak that would otherwise reach a report a client reads.
Both directions matter: secrets must go, and the surrounding structure must
survive — `Authorization: Bearer [REDACTED]` still proves the request was
authenticated, which is frequently the point of the evidence.
"""
import pytest

import redaction
from redaction import PLACEHOLDER, redact_mapping, redact_text


def _clean(text: str) -> bool:
    return not redaction.contains_obvious_secret(text)


# --------------------------------------------------------------------------- #
# Headers
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "header",
    [
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def",
        "authorization: Basic dXNlcjpwYXNz",
        "Cookie: session=abc123; other=def456",
        "Set-Cookie: sid=secret; HttpOnly",
        "X-API-Key: sk_live_9f8e7d6c5b4a",
        "Proxy-Authorization: Bearer topsecrettoken",
    ],
)
def test_sensitive_header_values_are_removed(header):
    out = redact_text(header)
    assert PLACEHOLDER in out
    name = header.split(":", 1)[0]
    assert out.startswith(name), "the header name must survive"
    assert header.split(":", 1)[1].strip() not in out


def test_cookie_header_loses_the_whole_value_not_just_one_pair():
    """`a=1; b=2` must not survive by having each pair matched individually."""
    out = redact_text("Cookie: session=abc123; tracking=xyz789")
    assert "abc123" not in out and "xyz789" not in out


def test_ordinary_headers_are_untouched():
    exchange = "Host: api.acme.com\nUser-Agent: curl/8.0\nAccept: application/json"
    assert redact_text(exchange) == exchange


def test_request_structure_survives_redaction():
    raw = (
        "GET /api/v1/users/42 HTTP/1.1\n"
        "Host: api.acme.com\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig\n"
        "Accept: application/json"
    )
    out = redact_text(raw)
    assert "GET /api/v1/users/42 HTTP/1.1" in out
    assert "Host: api.acme.com" in out
    assert "Authorization:" in out and PLACEHOLDER in out
    assert _clean(out)


# --------------------------------------------------------------------------- #
# Bodies and query strings
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "body",
    [
        '{"password": "hunter2"}',
        '{"access_token": "ya29.a0AfH6SMB"}',
        '{"client_secret": "cs_live_abc123"}',
        "username=admin&password=hunter2",
        '{"api_key": "sk_test_1234567890"}',
    ],
)
def test_sensitive_body_keys_are_removed(body):
    out = redact_text(body)
    assert PLACEHOLDER in out
    for leaked in ("hunter2", "ya29.a0AfH6SMB", "cs_live_abc123", "sk_test_1234567890"):
        assert leaked not in out


def test_non_sensitive_body_fields_survive():
    out = redact_text('{"username": "admin", "password": "hunter2"}')
    assert "admin" in out, "the finding often depends on which user was used"
    assert "hunter2" not in out


# --------------------------------------------------------------------------- #
# Shape-based detection — secrets with no key name to match on
# --------------------------------------------------------------------------- #

def test_bare_jwt_is_redacted_without_a_surrounding_key():
    raw = "response body contained eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature here"
    out = redact_text(raw)
    assert "eyJhbGciOiJIUzI1NiJ9" not in out and _clean(out)


def test_url_credentials_are_stripped():
    out = redact_text("curl https://admin:hunter2@api.acme.com/v1")
    assert "hunter2" not in out and "admin" not in out
    assert "api.acme.com/v1" in out, "the target must remain visible"


def test_bearer_token_in_prose_is_redacted():
    out = redact_text("I replayed it with Bearer abcdef1234567890 and it worked")
    assert "abcdef1234567890" not in out and _clean(out)


# --------------------------------------------------------------------------- #
# Structured data
# --------------------------------------------------------------------------- #

def test_mapping_redaction_is_recursive():
    data = {
        "method": "POST",
        "headers": {"Authorization": "Bearer secrettoken", "Accept": "*/*"},
        "body": {"user": {"name": "admin", "password": "hunter2"}},
    }
    out = redact_mapping(data)
    assert out["headers"]["Authorization"] == PLACEHOLDER
    assert out["headers"]["Accept"] == "*/*"
    assert out["body"]["user"]["password"] == PLACEHOLDER
    assert out["body"]["user"]["name"] == "admin"
    assert out["method"] == "POST"


def test_mapping_redaction_handles_lists():
    data = {"items": [{"token": "abc"}, {"safe": "ok"}]}
    out = redact_mapping(data)
    assert out["items"][0]["token"] == PLACEHOLDER
    assert out["items"][1]["safe"] == "ok"


def test_configurable_extra_keys_are_honoured():
    """Organizations have field names we cannot know in advance."""
    out = redact_text('{"internal_ref": "IR-9931"}', extra_keys=frozenset({"internal_ref"}))
    assert "IR-9931" not in out


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value", [None, ""])
def test_empty_input_is_safe(value):
    assert redact_text(value) == ""


def test_redaction_is_idempotent():
    once = redact_text("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.a.b")
    assert redact_text(once) == once


def test_detector_agrees_with_the_redactor():
    raw = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
    assert redaction.contains_obvious_secret(raw)
    assert not redaction.contains_obvious_secret(redact_text(raw))


# --------------------------------------------------------------------------- #
# Regressions — reported database-bound leaks
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "body,secret",
    [
        ('{"password":"hunter 2"}', "hunter 2"),
        ('{"api_key":"sk_live_abcd,efgh"}', "sk_live_abcd,efgh"),
        ('{"password": "a b c, d"}', "a b c, d"),
        ('{"client_secret":"cs,live abc"}', "cs,live abc"),
        ("password: my long passphrase here", "passphrase"),
        ('{"a": 1, "token": abc123, "b": 2}', "abc123"),
    ],
)
def test_secrets_with_spaces_or_punctuation_are_redacted(body, secret):
    """Reported leak: the value pattern excluded spaces and commas, so a match
    ended early and redaction never fired.

    Passphrases contain spaces and API keys contain punctuation — these were
    ordinary secrets, not exotic ones, and they reached the database verbatim.
    """
    out = redact_text(body)
    assert secret not in out
    assert PLACEHOLDER in out


def test_quoted_value_redaction_does_not_corrupt_surrounding_json():
    """The bare-value pattern must not re-chew a placeholder the quoted pattern
    already inserted — that produced malformed output."""
    out = redact_text('{"username": "admin", "password": "hunter2"}')
    assert out.count(PLACEHOLDER) == 1
    assert out.endswith('"}')
    assert "admin" in out


def test_surrounding_structure_survives_bare_value_redaction():
    out = redact_text('{"a": 1, "token": abc, "b": 2}')
    assert '"a": 1' in out and '"b": 2' in out and "abc" not in out
