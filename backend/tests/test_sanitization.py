"""Input sanitization — XSS, injection patterns, and null bytes are blocked or stripped."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest

from security import strip_html, sanitize_identifier, validate_safe_url
from routers.radar import _parse_bugcrowd, _safe_radar_url


def test_strip_html_none_returns_empty():
    assert strip_html(None) == ""


def test_strip_html_empty_string_returns_empty():
    assert strip_html("") == ""


def test_sanitize_identifier_none_returns_empty():
    assert sanitize_identifier(None) == ""


def test_sanitize_identifier_empty_string_returns_empty():
    assert sanitize_identifier("") == ""


def test_script_tag_in_program_name_rejected(client, auth_headers):
    res = client.post("/programs", json={"name": "<script>alert(1)</script>"}, headers=auth_headers)
    assert res.status_code == 422


def test_iframe_in_program_name_rejected(client, auth_headers):
    res = client.post("/programs", json={"name": "<iframe src=x>"}, headers=auth_headers)
    assert res.status_code == 422


def test_javascript_protocol_in_program_url_rejected(client, auth_headers):
    res = client.post("/programs", json={"name": "Safe Name", "program_url": "javascript:alert(1)"}, headers=auth_headers)
    assert res.status_code == 422


def test_data_url_in_program_url_rejected(client, auth_headers):
    res = client.post("/programs", json={"name": "Safe", "program_url": "data:text/html,<script>alert(1)</script>"}, headers=auth_headers)
    assert res.status_code == 422


def test_obfuscated_scheme_in_program_url_rejected(client, auth_headers):
    res = client.post("/programs", json={"name": "Safe", "program_url": "java\tscript:alert(1)"}, headers=auth_headers)
    assert res.status_code == 422


def test_valid_https_program_url_accepted(client, auth_headers):
    res = client.post("/programs", json={"name": "Safe", "program_url": "https://hackerone.com/acme"}, headers=auth_headers)
    assert res.status_code == 200
    client.delete(f"/programs/{res.json()['id']}", headers=auth_headers)


@pytest.mark.parametrize("good", ["https://example.com/x", "http://example.com", "", None])
def test_validate_safe_url_allows_http_https(good):
    assert validate_safe_url(good) == (good or "")


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)", "JavaScript:alert(1)", " javascript:alert(1)",
    "java\tscript:alert(1)", "data:text/html,x", "vbscript:msgbox(1)",
    "file:///etc/passwd", "//evil.com", "ftp://x.com",
])
def test_validate_safe_url_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        validate_safe_url(bad)


def test_radar_neutralizes_malicious_url_to_fallback():
    assert _safe_radar_url("javascript:alert(1)", "https://bugcrowd.com/x") == "https://bugcrowd.com/x"
    assert _safe_radar_url("https://bugcrowd.com/legit", "https://bugcrowd.com/x") == "https://bugcrowd.com/legit"
    assert _safe_radar_url("", "https://bugcrowd.com/x") == "https://bugcrowd.com/x"


def test_radar_parser_drops_hostile_program_url():
    out = _parse_bugcrowd([{"code": "evil", "name": "Evil", "program_url": "javascript:alert(1)"}])
    assert out[0]["url"] == "https://bugcrowd.com/evil"


def test_heartbeat_rejects_overlong_hostname(client, auth_headers):
    res = client.post("/runner/heartbeat", json={"hostname": "a" * 201}, headers=auth_headers)
    assert res.status_code == 422


def test_settings_rejects_overlong_webhook_url(client, auth_headers):
    res = client.patch("/settings", json={"webhook_url": "https://x.com/" + "a" * 600}, headers=auth_headers)
    assert res.status_code == 422


def test_submission_rejects_xss_platform_reference(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/submissions",
                      json={"title": "ref test", "platform_reference": "javascript:alert(1)"}, headers=auth_headers)
    assert res.status_code == 422


def test_event_handler_in_scope_value_rejected(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/scope/in",
        json={"value": 'example.com" onmouseover="alert(1)', "kind": "domain"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_xss_in_finding_title_rejected(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/findings",
        json={"title": "<img src=x onerror=alert(1)>", "severity": "high"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_html_tags_in_finding_summary_stripped(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/findings",
        json={"title": "Valid Title", "severity": "low", "summary": "<b>bold</b> text"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    # bleach strips tags — plain text should survive
    assert "bold" in res.json()["summary"]
    assert "<b>" not in res.json()["summary"]


def test_null_byte_in_program_name_stripped(client, auth_headers):
    res = client.post("/programs", json={"name": "Name\x00WithNull"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "\x00" not in data["name"]
    client.delete(f"/programs/{data['id']}", headers=auth_headers)
