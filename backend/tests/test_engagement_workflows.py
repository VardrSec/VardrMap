"""Cross-resource contracts for report snapshots, retests and reviewed case drafts."""
import copy
import hashlib
import json

import pytest


def finding(client, headers, pid):
    res = client.post(f"/engagements/{pid}/findings", headers=headers, json={"title": "Original issue", "severity": "high", "summary": "Original observation"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def report(client, headers, pid, **extra):
    res = client.post(f"/engagements/{pid}/deliverables", headers=headers, json={"title": "Client assessment", "executive_summary": "Risk summary", "methodology": "Manual testing", "limitations": "Staging only", "remediation_priorities": "Fix access checks", **extra})
    assert res.status_code == 201, res.text
    return res.json()


def test_report_freezes_complete_content_and_new_revision_refreshes(client, auth_headers, program_id):
    fid = finding(client, auth_headers, program_id)
    ev = client.post(f"/engagements/{program_id}/evidence", headers=auth_headers, json={"finding_id": fid, "title": "Request", "kind": "http_request", "body": "Authorization: Bearer test-fixture-secret"}).json()
    first = report(client, auth_headers, program_id, evidence_ids=[ev["id"]])
    path = f"/engagements/{program_id}/deliverables/{first['deliverable_id']}/revisions"
    assert "test-fixture-secret" not in json.dumps(first)
    for heading in ("Executive summary", "Scope and authorization", "Methodology", "Limitations", "Findings", "Selected evidence", "Remediation priorities"):
        assert f"## {heading}" in first["markdown"]
    client.patch(f"/engagements/{program_id}/findings/{fid}", headers=auth_headers, json={"title": "Updated issue"})
    frozen = client.get(f"{path}/1", headers=auth_headers).json()
    assert frozen == first
    exported = client.get(f"{path}/1/markdown", headers=auth_headers)
    assert exported.text == first["markdown"]
    assert hashlib.sha256(exported.content).hexdigest() == first["content_hash"]
    second = client.post(path, headers=auth_headers, json={"title": "Updated assessment", "base_revision": 1})
    assert second.status_code == 201, second.text
    assert second.json()["snapshot"]["findings"][0]["title"] == "Updated issue"
    assert client.post(path, headers=auth_headers, json={"title": "Stale edit", "base_revision": 1}).status_code == 409
    assert client.patch(f"{path}/1", headers=auth_headers, json={"status": "delivered"}).json()["content_hash"] == first["content_hash"]
    assert client.patch(f"{path}/1", headers=auth_headers, json={"status": "draft", "markdown": "tamper"}).status_code == 422
    revisions = client.get(f"{path}?limit=1&offset=1", headers=auth_headers).json()
    assert revisions["total"] == 2 and revisions["revisions"][0]["revision"] == 1


def test_report_selection_and_cross_engagement_ids(client, auth_headers, program_id):
    finding(client, auth_headers, program_id)
    assert report(client, auth_headers, program_id, finding_ids=[])["snapshot"]["findings"] == []
    path = f"/engagements/{program_id}/deliverables"
    for selection in ({"finding_ids": ["missing"]}, {"evidence_ids": ["missing"]}):
        assert client.post(path, headers=auth_headers, json={"title": "Report", **selection}).status_code == 404


def test_retests_retain_original_history_without_automatically_closing(client, auth_headers, program_id):
    fid = finding(client, auth_headers, program_id)
    path = f"/engagements/{program_id}/findings/{fid}"
    client.patch(path, headers=auth_headers, json={"summary": "Edited observation"})
    ev = client.post(f"/engagements/{program_id}/evidence", headers=auth_headers, json={"finding_id": fid, "title": "Retest response", "body": "403 Forbidden"}).json()
    for kind, outcome in (("remediation", None), ("retest", "still_open"), ("retest", "verified_fixed")):
        res = client.post(path + "/activity", headers=auth_headers, json={"kind": kind, "outcome": outcome, "notes": "Authorization: Bearer fixture-secret", "evidence_ids": [ev["id"]]})
        assert res.status_code == 201, res.text
        assert "fixture-secret" not in res.text
        assert res.json()["evidence"][0]["content_hash"] == ev["content_hash"]
    data = client.get(path + "/activity?limit=2", headers=auth_headers).json()
    assert data["total"] == 5 and len(data["activities"]) == 2
    original = client.get(path + "/activity?offset=4", headers=auth_headers).json()["activities"][0]
    assert original["snapshot"]["summary"] == "Original observation"
    rows = client.get(f"/engagements/{program_id}/findings", headers=auth_headers).json()["findings"]
    assert rows[0]["status"] == "new"
    for payload in ({"kind": "retest", "notes": "Missing outcome"}, {"kind": "remediation", "notes": "Bad outcome", "outcome": "verified_fixed"}, {"kind": "retest", "outcome": "inconclusive", "notes": "   "}):
        assert client.post(path + "/activity", headers=auth_headers, json=payload).status_code == 400
    assert client.post(path + "/activity", headers=auth_headers, json={"kind": "remediation", "notes": "Update", "evidence_ids": ["missing"]}).status_code == 404


def document():
    return {"openapi": "3.1.0", "servers": [{"url": "https://api.example.test/v1"}], "paths": {"/accounts/{id}": {"get": {"responses": {"200": {"description": "Visible"}}}, "delete": {}}, "/health": {"get": {}}}}


def preview(client, headers, pid, **extra):
    res = client.post(f"/engagements/{pid}/test-cases/preview", headers=headers, json={"openapi": document(), **extra})
    assert res.status_code == 200, res.text
    return res.json()


def test_drafts_are_paginated_inert_and_require_review(client, auth_headers, program_id):
    page = preview(client, auth_headers, program_id, limit=1, offset=1)
    assert page["total"] == 3 and page["next_offset"] == 2
    draft = page["drafts"][0]
    assert draft["spec"]["mutating"] is True
    assert {e["decision"] for e in draft["spec"]["expected_access"]} == {"skip"}
    path = f"/engagements/{program_id}/test-cases"
    assert client.get(path, headers=auth_headers).json()["test_cases"] == []
    assert client.post(path + "/reviewed", headers=auth_headers, json={"cases": [draft]}).status_code == 422
    payload = {"reviewed": True, "cases": [draft]}
    assert client.post(path + "/reviewed", headers=auth_headers, json=payload).status_code == 400
    draft["spec"]["request"]["url"] = "https://api.example.test/v1/accounts/42"
    assert client.post(path + "/reviewed", headers=auth_headers, json=payload).status_code == 400
    draft["spec"]["expected_access"][0]["decision"] = "deny"
    res = client.post(path + "/reviewed", headers=auth_headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json()["test_cases"][0]["spec"] == draft["spec"]
    assert client.get(f"/engagements/{program_id}/jobs", headers=auth_headers).json()["jobs"] == []


def test_reviewed_batch_is_atomic_and_rejects_literal_credentials(client, auth_headers, program_id):
    draft = preview(client, auth_headers, program_id, offset=2)["drafts"][0]
    draft["spec"]["expected_access"][0]["decision"] = "allow"
    bad = copy.deepcopy(draft)
    bad["spec"]["identities"][1]["credential"] = {"type": "bearer", "value": "literal-fixture"}
    path = f"/engagements/{program_id}/test-cases"
    assert client.post(path + "/reviewed", headers=auth_headers, json={"reviewed": True, "cases": [draft, bad]}).status_code == 400
    assert client.get(path, headers=auth_headers).json()["test_cases"] == []


@pytest.mark.parametrize("doc,base", [({"openapi": "2.0", "paths": {}}, ""), ({"openapi": "3.0.0", "paths": {"/x": {"$ref": "https://example.test/schema"}}}, ""), ({"openapi": "3.0.0", "paths": {"/x": {"get": {}}}}, "https://user:pass@example.test"), ({"openapi": "3.0.0", "paths": []}, "")])
def test_invalid_openapi_is_reported_without_fetching(client, auth_headers, program_id, doc, base):
    assert client.post(f"/engagements/{program_id}/test-cases/preview", headers=auth_headers, json={"openapi": doc, "base_url": base}).status_code == 400


@pytest.mark.parametrize("suffix", ["deliverables", "test-cases/preview", "findings/{fid}/activity"])
def test_new_workflows_auth_and_tenant_isolation(client, auth_headers, other_headers, program_id, suffix):
    fid = finding(client, auth_headers, program_id)
    path = f"/engagements/{program_id}/{suffix.format(fid=fid)}"
    payload = {"title": "Report"} if suffix == "deliverables" else {"openapi": document()} if suffix == "test-cases/preview" else {"kind": "remediation", "notes": "Update"}
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, json=payload, headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post(path, json=payload, headers=other_headers).status_code == 404
    key = client.post("/auth/apikeys", headers=auth_headers, json={"label": "workflow test", "scope": "full"})
    assert key.status_code in (200, 201), key.text
    token = key.json()["token"]
    client.delete(f"/auth/apikeys/{key.json()['id']}", headers=auth_headers)
    assert client.post(path, json=payload, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_viewer_can_read_but_cannot_write_workflows(client, auth_headers, other_headers, program_id):
    client.get("/me", headers=other_headers)
    fid = finding(client, auth_headers, program_id)
    res = client.post(f"/engagements/{program_id}/members", headers=auth_headers, json={"github_id": "gh_user2", "role": "viewer"})
    assert res.status_code in (200, 201), res.text
    first = report(client, auth_headers, program_id)
    base = f"/engagements/{program_id}"
    revision = f"{base}/deliverables/{first['deliverable_id']}/revisions/1"
    assert client.get(revision, headers=other_headers).status_code == 200
    assert client.patch(revision, headers=other_headers, json={"status": "final"}).status_code == 403
    assert client.post(base + f"/findings/{fid}/activity", headers=other_headers, json={"kind": "remediation", "notes": "Update"}).status_code == 403
    assert client.post(base + "/deliverables", headers=other_headers, json={"title": "Report"}).status_code == 403
