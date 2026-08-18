"""The report lifecycle is a client-deliverable lifecycle, not a bounty verdict.

`draft -> internal_review -> final -> delivered`, with `archived` reachable from
any state. The retired values described what a bounty platform decided about a
submission (`submitted`, `accepted`, `duplicate`, `informative`, `resolved`);
migration `0022reportlifecycle` maps stored rows and these tests keep them from
coming back through the API.
"""
import typing

import pytest

from db import SessionLocal
from models import Report
from schemas import ReportStatus

CURRENT = list(typing.get_args(ReportStatus))
RETIRED = ["submitted", "accepted", "duplicate", "informative", "resolved", "rejected"]


def _create(client, headers, pid, **body):
    payload = {"title": "Deliverable"}
    payload.update(body)
    return client.post(f"/programs/{pid}/reports", json=payload, headers=headers)


# --------------------------------------------------------------------------- #
# The enum itself
# --------------------------------------------------------------------------- #

def test_lifecycle_is_exactly_the_deliverable_states():
    """Pins the vocabulary. Adding a bounty-ish value here fails loudly."""
    assert CURRENT == ["draft", "internal_review", "final", "delivered", "archived"]


@pytest.mark.parametrize("status", CURRENT)
def test_every_current_status_is_accepted_on_create(client, auth_headers, program_id, status):
    res = _create(client, auth_headers, program_id, status=status)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == status


@pytest.mark.parametrize("status", CURRENT)
def test_every_current_status_is_accepted_on_update(client, auth_headers, program_id, status):
    rid = _create(client, auth_headers, program_id).json()["id"]
    res = client.patch(
        f"/programs/{program_id}/reports/{rid}", json={"status": status}, headers=auth_headers
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == status


@pytest.mark.parametrize("status", RETIRED)
def test_retired_bounty_statuses_are_rejected_on_create(
    client, auth_headers, program_id, status
):
    res = _create(client, auth_headers, program_id, status=status)
    assert res.status_code == 422, (
        f"{status!r} is a retired bounty-submission outcome and must not be accepted."
    )


@pytest.mark.parametrize("status", RETIRED)
def test_retired_bounty_statuses_are_rejected_on_update(
    client, auth_headers, program_id, status
):
    rid = _create(client, auth_headers, program_id).json()["id"]
    res = client.patch(
        f"/programs/{program_id}/reports/{rid}", json={"status": status}, headers=auth_headers
    )
    assert res.status_code == 422


def test_unknown_status_is_rejected(client, auth_headers, program_id):
    assert _create(client, auth_headers, program_id, status="shipped").status_code == 422


def test_default_status_is_draft(client, auth_headers, program_id):
    res = _create(client, auth_headers, program_id)
    assert res.status_code == 200
    assert res.json()["status"] == "draft"


def test_archived_is_reachable_directly_from_draft(client, auth_headers, program_id):
    """A draft superseded before it ever reaches a client still needs somewhere
    to go — archived is not gated behind delivered."""
    rid = _create(client, auth_headers, program_id).json()["id"]
    res = client.patch(
        f"/programs/{program_id}/reports/{rid}", json={"status": "archived"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "archived"


# --------------------------------------------------------------------------- #
# Transitions are deliberately not enforced
# --------------------------------------------------------------------------- #
#
# These are independent workflow labels, not a state machine. Pinned as tests so
# the absence of enforcement is a documented guarantee rather than an oversight
# somebody "fixes" later — see the ReportStatus comment in schemas.py.

def test_a_report_can_be_created_directly_as_delivered(client, auth_headers, program_id):
    """Importing a report that was already handed over must not require walking
    it through draft, internal_review and final first."""
    res = _create(client, auth_headers, program_id, status="delivered")
    assert res.status_code == 200
    assert res.json()["status"] == "delivered"


def test_a_delivered_report_can_go_back_to_draft(client, auth_headers, program_id):
    """Client feedback re-opens deliverables; nothing blocks the reverse move."""
    rid = _create(client, auth_headers, program_id, status="delivered").json()["id"]
    res = client.patch(
        f"/programs/{program_id}/reports/{rid}", json={"status": "draft"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "draft"


def test_stages_may_be_skipped_in_either_direction(client, auth_headers, program_id):
    """draft -> delivered -> internal_review is accepted. Only the value is
    validated, never the path taken to it."""
    rid = _create(client, auth_headers, program_id).json()["id"]
    for status in ["delivered", "internal_review", "archived", "final"]:
        res = client.patch(
            f"/programs/{program_id}/reports/{rid}",
            json={"status": status},
            headers=auth_headers,
        )
        assert res.status_code == 200, f"{status} should be reachable from any state"
        assert res.json()["status"] == status


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def test_report_serializes_created_at(client, auth_headers, program_id):
    """Documented and used for ordering, but previously never returned."""
    res = _create(client, auth_headers, program_id)
    assert res.status_code == 200
    assert res.json().get("created_at"), "created_at must be present and populated"


def test_listed_reports_carry_created_at(client, auth_headers, program_id):
    _create(client, auth_headers, program_id)
    listed = client.get(f"/programs/{program_id}/reports", headers=auth_headers).json()["reports"]
    assert listed
    for report in listed:
        assert report.get("created_at"), "every listed report needs created_at"


def test_status_round_trips_through_the_list_endpoint(client, auth_headers, program_id):
    rid = _create(client, auth_headers, program_id, status="internal_review").json()["id"]
    listed = client.get(f"/programs/{program_id}/reports", headers=auth_headers).json()["reports"]
    match = next(r for r in listed if r["id"] == rid)
    assert match["status"] == "internal_review"


# --------------------------------------------------------------------------- #
# Migration 0022 — the mapping, exercised against the real function
# --------------------------------------------------------------------------- #

def test_migration_mapping_is_total_and_lands_on_current_statuses():
    """Every retired value maps somewhere, and only onto a value still accepted."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).parent.parent
        / "migrations" / "versions" / "0022_report_deliverable_lifecycle.py"
    )
    spec = importlib.util.spec_from_file_location("mig0022", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    retired_in_schema = {"submitted", "accepted", "duplicate", "informative", "resolved"}
    assert set(mig._FORWARD) == retired_in_schema, (
        "Every retired status must be mapped, or rows keep bounty vocabulary."
    )
    assert set(mig._FORWARD.values()) <= set(CURRENT), (
        "The migration must only produce statuses the schema still accepts."
    )
    # The intentional mapping, spelled out so a silent change fails here.
    assert mig._FORWARD["submitted"] == "delivered"
    assert mig._FORWARD["accepted"] == "delivered"
    assert mig._FORWARD["resolved"] == "delivered"
    assert mig._FORWARD["duplicate"] == "archived"
    assert mig._FORWARD["informative"] == "archived"
    # Reverse must not emit anything the old schema did not know.
    assert set(mig._BACKWARD.values()) <= {"draft", "submitted", "informative"}


def test_migration_forward_map_converts_stored_rows(client, auth_headers, program_id):
    """Write legacy values straight to the table (the API refuses them), then run
    the migration's mapping over them and confirm nothing bounty-shaped survives."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).parent.parent
        / "migrations" / "versions" / "0022_report_deliverable_lifecycle.py"
    )
    spec = importlib.util.spec_from_file_location("mig0022b", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    legacy = ["submitted", "accepted", "resolved", "duplicate", "informative"]
    db = SessionLocal()
    ids = []
    try:
        for value in legacy:
            row = Report(program_id=program_id, title=f"legacy {value}", status=value)
            db.add(row)
            db.flush()
            ids.append(row.id)
        db.commit()

        # Apply the same mapping the migration issues.
        for source, target in mig._FORWARD.items():
            db.query(Report).filter(
                Report.program_id == program_id, Report.status == source
            ).update({Report.status: target}, synchronize_session=False)
        db.commit()

        migrated = {
            r.title: r.status
            for r in db.query(Report).filter(Report.id.in_(ids)).all()
        }
    finally:
        db.close()

    assert migrated["legacy submitted"] == "delivered"
    assert migrated["legacy accepted"] == "delivered"
    assert migrated["legacy resolved"] == "delivered"
    assert migrated["legacy duplicate"] == "archived"
    assert migrated["legacy informative"] == "archived"
    assert set(migrated.values()) <= set(CURRENT)


def test_migrated_rows_serialize_and_are_patchable(client, auth_headers, program_id):
    """A migrated row must behave like any other report afterwards."""
    db = SessionLocal()
    try:
        row = Report(program_id=program_id, title="was submitted", status="delivered")
        db.add(row)
        db.commit()
        rid = row.id
    finally:
        db.close()

    fetched = client.get(f"/programs/{program_id}/reports", headers=auth_headers).json()["reports"]
    match = next(r for r in fetched if r["id"] == rid)
    assert match["status"] == "delivered"
    assert match["created_at"]

    res = client.patch(
        f"/programs/{program_id}/reports/{rid}", json={"status": "archived"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "archived"
