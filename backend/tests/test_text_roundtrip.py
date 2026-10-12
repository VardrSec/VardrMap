"""New text retains literal entity syntax without rewriting historical rows."""
import pytest
from audit_recon_urls import legacy_form
from security import sanitize_identifier, strip_html


@pytest.mark.parametrize("value", [
    "Terms & Conditions", "a&b", "a&amp;b", "a&#38;b", "a&#x26;b",
    "a&ampb", "literal &lt;b&gt;", "1 < 2 and 3 > 2",
])
@pytest.mark.parametrize("clean", [strip_html, sanitize_identifier])
def test_plain_text_roundtrips(value, clean):
    assert clean(value) == value
    assert clean(clean(value)) == value


def test_html_stripping_policy_remains():
    assert strip_html("<script>bad()</script><b>Terms & Conditions</b>") == "Terms & Conditions"
    assert strip_html("literal &lt;script&gt; is text") == "literal &lt;script&gt; is text"


def test_historical_audit_keeps_the_old_transformation():
    assert legacy_form("a&b") == legacy_form("a&#38;b") == "a&amp;b"
    assert strip_html("a&b") != strip_html("a&#38;b")


def test_finding_text_roundtrips_through_create_update_and_read(client, auth_headers, program_id):
    text = "Terms & Conditions, literal &amp; and ?a=1&b=2"
    base = f"/engagements/{program_id}/findings"
    response = client.post(base, headers=auth_headers, json={"title": text, "severity": "low", "summary": text})
    assert response.status_code == 200
    finding_id = response.json()["id"]
    assert response.json()["title"] == response.json()["summary"] == text
    response = client.patch(f"{base}/{finding_id}", headers=auth_headers, json={"summary": text})
    assert response.status_code == 200
    assert response.json()["summary"] == text
    rows = client.get(base, headers=auth_headers).json()["findings"]
    assert next(row for row in rows if row["id"] == finding_id)["summary"] == text
