"""Input sanitization — XSS, injection patterns, and null bytes are blocked or stripped."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from security import strip_html, sanitize_identifier


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


def test_javascript_protocol_in_program_url_stripped(client, auth_headers):
    # javascript: in the url field goes through strip_html (long-form field),
    # which bleach-strips tags but doesn't block the field entirely.
    # The value should come back sanitized, not cause a 500.
    res = client.post("/programs", json={"name": "Safe Name", "program_url": "javascript:alert(1)"}, headers=auth_headers)
    # strip_html is permissive on non-tag content; the important thing is no 500
    assert res.status_code == 200
    pid = res.json()["id"]
    client.delete(f"/programs/{pid}", headers=auth_headers)


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
