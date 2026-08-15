"""Evidence through the real API.

`test_redaction.py` proves the redactor. These prove it is actually applied at
the only door evidence comes through — and, critically, that the secret is
absent from the **stored row**, not merely from the response body. Redacting on
render would leave the raw value in the database for the next export or log line
to find.
"""
import pytest

import redaction
from db import SessionLocal
from models import Evidence

RAW_REQUEST = (
    "POST /api/v1/login HTTP/1.1\n"
    "Host: api.acme.com\n"
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig\n"
    "Cookie: session=supersecretvalue\n"
    "\n"
    '{"username": "admin", "password": "hunter2"}'
)


@pytest.fixture
def engagement(client, auth_headers):
    pid = client.post("/programs", json={"name": "Evidence"}, headers=auth_headers).json()["id"]
    yield pid
    client.delete(f"/programs/{pid}", headers=auth_headers)


def _post(client, headers, pid, **overrides):
    body = {"kind": "http_request", "title": "Login request", "body": RAW_REQUEST}
    body.update(overrides)
    return client.post(f"/programs/{pid}/evidence", json=body, headers=headers)


# --------------------------------------------------------------------------- #
# Redaction on write
# --------------------------------------------------------------------------- #

def test_evidence_is_created(client, auth_headers, engagement):
    assert _post(client, auth_headers, engagement).status_code == 201


def test_response_contains_no_secrets(client, auth_headers, engagement):
    body = _post(client, auth_headers, engagement).json()["body"]
    for secret in ("eyJhbGciOiJIUzI1NiJ9", "supersecretvalue", "hunter2"):
        assert secret not in body
    assert not redaction.contains_obvious_secret(body)


def test_stored_row_contains_no_secrets(client, auth_headers, engagement):
    """The one that matters. Redacting on render would leave this row poisoned."""
    evidence_id = _post(client, auth_headers, engagement).json()["id"]
    db = SessionLocal()
    try:
        stored = db.query(Evidence).filter(Evidence.id == evidence_id).first().body
    finally:
        db.close()
    for secret in ("eyJhbGciOiJIUzI1NiJ9", "supersecretvalue", "hunter2"):
        assert secret not in stored
    assert not redaction.contains_obvious_secret(stored)


def test_evidence_keeps_the_structure_that_proves_the_finding(
    client, auth_headers, engagement
):
    body = _post(client, auth_headers, engagement).json()["body"]
    assert "POST /api/v1/login HTTP/1.1" in body
    assert "Host: api.acme.com" in body
    assert "Authorization:" in body, "that the request was authenticated is the point"
    assert "admin" in body, "which identity was used is often the finding"


def test_content_hash_covers_the_stored_body(client, auth_headers, engagement):
    import hashlib

    created = _post(client, auth_headers, engagement).json()
    assert created["content_hash"] == hashlib.sha256(created["body"].encode()).hexdigest()


def test_redacted_flag_is_set(client, auth_headers, engagement):
    assert _post(client, auth_headers, engagement).json()["redacted"] is True


def test_note_kind_also_strips_html(client, auth_headers, engagement):
    res = _post(
        client, auth_headers, engagement,
        kind="note", body="<script>alert(1)</script>analyst note",
    )
    assert "<script>" not in res.json()["body"]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("field,value", [
    ("kind", "malware"),
    ("sensitivity", "cosmic-top-secret"),
    ("retention", "forever-and-ever"),
])
def test_invalid_enum_values_are_rejected(client, auth_headers, engagement, field, value):
    assert _post(client, auth_headers, engagement, **{field: value}).status_code == 400


def test_oversized_body_is_rejected(client, auth_headers, engagement):
    """A pasted 50MB response must not become a row."""
    res = _post(client, auth_headers, engagement, body="A" * 200_001)
    assert res.status_code == 422


def test_finding_from_another_engagement_is_rejected(client, auth_headers, engagement):
    other = client.post("/programs", json={"name": "Other"}, headers=auth_headers).json()["id"]
    finding = client.post(
        f"/programs/{other}/findings",
        json={"title": "Foreign", "severity": "low"},
        headers=auth_headers,
    )
    try:
        if finding.status_code in (200, 201):
            res = _post(
                client, auth_headers, engagement, finding_id=finding.json()["id"]
            )
            assert res.status_code == 400
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)


# --------------------------------------------------------------------------- #
# Access control
# --------------------------------------------------------------------------- #

def test_stranger_cannot_create_evidence(client, other_headers, engagement):
    assert _post(client, other_headers, engagement).status_code == 404


def test_stranger_cannot_list_evidence(client, other_headers, engagement):
    assert client.get(
        f"/programs/{engagement}/evidence", headers=other_headers
    ).status_code == 404


def test_list_and_delete_round_trip(client, auth_headers, engagement):
    evidence_id = _post(client, auth_headers, engagement).json()["id"]

    listed = client.get(f"/programs/{engagement}/evidence", headers=auth_headers)
    assert listed.json()["total"] == 1

    deleted = client.delete(
        f"/programs/{engagement}/evidence/{evidence_id}", headers=auth_headers
    )
    assert deleted.status_code == 200
    assert client.get(
        f"/programs/{engagement}/evidence", headers=auth_headers
    ).json()["total"] == 0


def test_deleting_another_engagements_evidence_is_404(client, auth_headers, engagement):
    other = client.post("/programs", json={"name": "Other2"}, headers=auth_headers).json()["id"]
    foreign_id = _post(client, auth_headers, other).json()["id"]
    try:
        res = client.delete(
            f"/programs/{engagement}/evidence/{foreign_id}", headers=auth_headers
        )
        assert res.status_code == 404
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)
