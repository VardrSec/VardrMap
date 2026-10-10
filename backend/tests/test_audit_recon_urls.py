"""The recon-URL audit: it measures what can be corroborated, and it changes nothing."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError

import audit_recon_urls as audit_mod
from db import get_db
from main import app
from models import ReconItem, ScanItem

LEGACY = "https://t.test/a?x=1&amp;y=2"
CORRECT = "https://t.test/a?x=1&y=2"


@pytest.fixture
def db():
    session = next(app.dependency_overrides[get_db]())
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _row(db, program_id, url, source="gau", created=None):
    row = ReconItem(
        program_id=program_id, source=source, url=url, host="t.test",
        created_at=created or datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    db.commit()
    return row.id


def _gau(report):
    return report["recon"]["gau"]


def test_a_legacy_row_with_a_matching_correct_row_is_corroborated(db, program_id):
    _row(db, program_id, LEGACY)
    _row(db, program_id, CORRECT)
    stats = _gau(audit_mod.audit(db))
    assert (stats["rows"], stats["suspect"], stats["corroborated"], stats["unpaired"]) == (2, 1, 1, 0)


def test_a_legacy_row_with_no_evidence_is_unpaired(db, program_id):
    _row(db, program_id, LEGACY)
    stats = _gau(audit_mod.audit(db))
    assert (stats["suspect"], stats["corroborated"], stats["unpaired"]) == (1, 0, 1)


def test_rows_without_encoded_characters_are_not_counted(db, program_id):
    _row(db, program_id, "https://t.test/plain?x=1")
    _row(db, program_id, CORRECT)  # raw '&' is how a fixed import stores it
    assert _gau(audit_mod.audit(db))["marked"] == 0


def test_two_originals_sharing_one_stored_value_are_reported_as_a_collision(db, program_id):
    """`a&b` and `a&#38;b` both became `a&amp;b`: the stored row cannot say which it was."""
    _row(db, program_id, "https://t.test/c?x=1&amp;y=2")
    _row(db, program_id, "https://t.test/c?x=1&y=2")
    _row(db, program_id, "https://t.test/c?x=1&#38;y=2")
    stats = _gau(audit_mod.audit(db))
    assert stats["collisions"] == 1 and stats["corroborated"] == 1


def test_a_peer_in_another_engagement_is_not_evidence(db, program_id, client, auth_headers):
    other = client.post("/programs", json={"name": "Other"}, headers=auth_headers).json()["id"]
    try:
        _row(db, program_id, LEGACY)
        _row(db, other, CORRECT)
        assert _gau(audit_mod.audit(db))["unpaired"] == 1
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)


def test_a_row_created_after_the_fix_is_a_literal_entity_not_corruption(db, program_id):
    """A genuine `&amp;` imported after the fix is indistinguishable by content alone."""
    cutoff = datetime(2026, 10, 11)
    _row(db, program_id, LEGACY, created=cutoff - timedelta(days=1))
    _row(db, program_id, "https://t.test/z?a=1&amp;b=2", created=cutoff + timedelta(days=1))
    report = audit_mod.audit(db, cutoff)
    assert _gau(report)["marked"] == 2 and _gau(report)["suspect"] == 1


def test_nuclei_scan_items_are_counted(db, program_id):
    db.add(ScanItem(program_id=program_id, source="nuclei", asset=LEGACY, matched_at=LEGACY))
    db.add(ScanItem(program_id=program_id, source="dalfox", asset=LEGACY))  # stored raw: not counted
    db.commit()
    assert audit_mod.audit(db)["nuclei_scan_items_suspect"] == 1


def test_the_audit_changes_nothing_and_cannot_write(db, program_id):
    _row(db, program_id, LEGACY)
    _row(db, program_id, CORRECT)
    before = sorted((r.id, r.url) for r in db.query(ReconItem).filter_by(program_id=program_id))
    audit_mod.audit(db)
    after = sorted((r.id, r.url) for r in db.query(ReconItem).filter_by(program_id=program_id))
    assert before == after

    # While in read-only mode a write must fail rather than succeed.
    audit_mod.make_read_only(db)
    try:
        db.add(ReconItem(program_id=program_id, source="gau", url="https://t.test/nope"))
        with pytest.raises(OperationalError):
            db.flush()
    finally:
        db.rollback()
        audit_mod.restore_writes(db)


def test_the_audit_leaves_the_connection_writable_afterwards(db, program_id):
    """SQLite's pragma is per-connection; leaking it would break whatever ran next."""
    audit_mod.audit(db)
    _row(db, program_id, "https://t.test/after-audit")  # would raise if still read-only


def test_an_unknown_database_is_refused_rather_than_audited(db, monkeypatch):
    class Dialect:
        name = "oracle"

    class Bind:
        dialect = Dialect()

    monkeypatch.setattr(db, "get_bind", lambda *a, **k: Bind())
    with pytest.raises(RuntimeError, match="read-only"):
        audit_mod.make_read_only(db)


def test_the_summary_says_what_it_cannot_see(db, program_id):
    _row(db, program_id, LEGACY)
    out = audit_mod.render(audit_mod.audit(db))
    assert "unpaired" in out and "Irrecoverable" in out and "no --fixed-since" in out
