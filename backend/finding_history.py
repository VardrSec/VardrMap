"""Append-only finding history, with secrets removed before persistence."""
from models import FindingActivity
from redaction import redact_text
from serializers import serialize_finding


def clean_tree(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [clean_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_tree(item) for key, item in value.items()}
    return value


def record(db, finding, actor: str, kind: str, notes: str = "", outcome=None, evidence=None):
    entry = FindingActivity(
        program_id=finding.program_id, finding_id=finding.id, actor=actor,
        kind=kind, notes=redact_text(notes), outcome=outcome,
        snapshot=clean_tree(serialize_finding(finding)), evidence=evidence or [],
    )
    db.add(entry)
    return entry


def capture_baseline(db, finding, actor: str):
    if not db.query(FindingActivity.id).filter(FindingActivity.finding_id == finding.id).first():
        record(db, finding, actor, "baseline", "State when history tracking began.")
        db.flush()


def serialize(entry):
    return {
        "id": entry.id, "kind": entry.kind, "outcome": entry.outcome,
        "notes": entry.notes, "actor": entry.actor, "snapshot": entry.snapshot,
        "evidence": entry.evidence, "created_at": entry.created_at.isoformat(),
    }
