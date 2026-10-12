"""Contracts exercised by the real Map -> Runner -> Gate acceptance run."""
import pytest

from db import SessionLocal
from models import AuditLog, EngagementMember
from tests.test_vardrgate_jobs import _RESULT, _queued_job, _store_case, _upload


@pytest.mark.parametrize("value,code", [(None, 200), ([], 200), ({}, 422), ("", 422), (False, 422)])
def test_gate_findings_wire_shape(client, auth_headers, program_id, value, code):
    job = _queued_job(client, auth_headers, program_id)
    result = _upload(client, auth_headers, job, {**_RESULT, "findings": value})
    assert result.status_code == code, result.text
    if code == 200:
        assert result.json()["scan_items_created"] == 0
        assert result.json()["evidence_created"] == 2


@pytest.mark.parametrize("value,code", [(1, 200), (86400, 200), (0, 400), (86401, 400), (True, 400), (1.5, 400), ("5", 400), (None, 400)])
def test_gate_queue_timeout(client, auth_headers, program_id, value, code):
    tc = _store_case(client, auth_headers, program_id)
    result = client.post(f"/engagements/{program_id}/jobs", headers=auth_headers, json={
        "tool_type": "vardrgate_api_test", "target_source": "scope",
        "config": {"test_case_id": tc, "timeout": value},
    })
    assert result.status_code == code, result.text


@pytest.mark.parametrize("kind", ["target_stats", "target_warning", "blocked"])
def test_runner_event_types_persist(client, auth_headers, program_id, kind):
    job = _queued_job(client, auth_headers, program_id)
    result = client.post(f"/jobs/{job}/events", headers=auth_headers, json={"kind": kind, "text": "local check"})
    assert result.status_code == 201, result.text
    events = client.get(f"/jobs/{job}/events", headers=auth_headers).json()["events"]
    assert any(e["kind"] == kind for e in events)


def _resources(client, headers, pid):
    job = _queued_job(client, headers, pid)
    assert _upload(client, headers, job).status_code == 200
    evidence = client.get(f"/engagements/{pid}/evidence", headers=headers).json()["evidence"][0]
    finding = client.post(f"/engagements/{pid}/findings", headers=headers, json={"title": "Reviewed authorization issue", "severity": "high"}).json()
    return evidence, finding["id"]


def test_link_preserves_provenance_and_enables_retest(client, auth_headers, program_id):
    evidence, fid = _resources(client, auth_headers, program_id)
    path = f"/engagements/{program_id}/evidence/{evidence['id']}/link"
    result = client.post(path, headers=auth_headers, json={"finding_id": fid})
    assert result.status_code == 200, result.text
    assert result.json() == {**evidence, "finding_id": fid}
    assert client.post(path, headers=auth_headers, json={"finding_id": fid}).json() == result.json()
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(resource_id=evidence["id"], action="link").count() == 1
    activity = client.post(f"/engagements/{program_id}/findings/{fid}/activity", headers=auth_headers, json={
        "kind": "retest", "outcome": "still_open", "notes": "Reviewed scan evidence", "evidence_ids": [evidence["id"]],
    })
    assert activity.status_code == 201, activity.text
    other_fid = client.post(f"/engagements/{program_id}/findings", headers=auth_headers, json={"title": "Other", "severity": "low"}).json()["id"]
    assert client.post(path, headers=auth_headers, json={"finding_id": other_fid}).status_code == 409


def test_link_auth_and_tenant_isolation(client, auth_headers, other_headers, program_id):
    evidence, fid = _resources(client, auth_headers, program_id)
    path = f"/engagements/{program_id}/evidence/{evidence['id']}/link"
    payload = {"finding_id": fid}
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, headers={"Authorization": "Bearer invalid"}, json=payload).status_code == 401
    assert client.post(path, headers=other_headers, json=payload).status_code == 404
    foreign = client.post("/engagements", headers=auth_headers, json={"name": "Separate engagement"}).json()["id"]
    try:
        foreign_e, foreign_fid = _resources(client, auth_headers, foreign)
        assert client.post(path, headers=auth_headers, json={"finding_id": foreign_fid}).status_code == 404
        assert client.post(f"/engagements/{program_id}/evidence/{foreign_e['id']}/link", headers=auth_headers, json=payload).status_code == 404
    finally:
        client.delete(f"/engagements/{foreign}", headers=auth_headers)


def test_link_member_permissions_and_revocation(client, auth_headers, other_headers, program_id):
    evidence, fid = _resources(client, auth_headers, program_id)
    path = f"/engagements/{program_id}/evidence/{evidence['id']}/link"
    with SessionLocal() as db:
        member = EngagementMember(program_id=program_id, owner_github_id="gh_user1", member_github_id="gh_user2", role="viewer")
        db.add(member)
        db.commit()
    assert client.post(path, headers=other_headers, json={"finding_id": fid}).status_code == 403
    with SessionLocal() as db:
        db.query(EngagementMember).filter_by(program_id=program_id, member_github_id="gh_user2").update({"role": "member"})
        db.commit()
    assert client.post(path, headers=other_headers, json={"finding_id": fid}).status_code == 200
    with SessionLocal() as db:
        db.query(EngagementMember).filter_by(program_id=program_id, member_github_id="gh_user2").delete()
        db.commit()
    assert client.post(path, headers=other_headers, json={"finding_id": fid}).status_code == 404
