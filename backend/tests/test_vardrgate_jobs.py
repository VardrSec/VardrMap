"""VardrGate jobs: queueing against a stored case, spec inlining, result upload.

Three things are load-bearing here and each has a test that fails if it breaks:

1. `GET /jobs/pending` inlines the stored spec, because VardrRunner's config
   parser requires `test_case` as an object. Without it the integration needs a
   VardrRunner release.
2. The inlined spec is *not* written back to `scan_jobs.config`, which must keep
   holding only the id.
3. Uploaded results are redacted on write and land as triageable `scan_items`
   plus backing `evidence`.
"""
from db import SessionLocal
from models import Evidence, ScanItem, ScanJob


def _spec(case_id: str = "bola-check") -> dict:
    return {
        "id": case_id,
        "identities": [
            {"id": "admin", "credential": {"type": "bearer", "value_env": "ADMIN_TOKEN"}},
            {"id": "attacker", "credential": {"type": "bearer", "value_keychain": "atk"}},
        ],
        "request": {"method": "GET", "url": "https://api.example.com/users/42/profile"},
        "expected_access": [
            {"identity_id": "admin", "decision": "allow"},
            {"identity_id": "attacker", "decision": "deny"},
        ],
    }


def _store_case(client, headers, pid, case_id: str = "bola-check") -> str:
    res = client.post(
        f"/programs/{pid}/test-cases",
        json={"name": "BOLA", "spec": _spec(case_id)},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _queue(client, headers, pid, tc_id: str):
    return client.post(
        f"/programs/{pid}/jobs",
        json={
            "tool_type": "vardrgate_api_test",
            "target_source": "scope",
            "config": {"test_case_id": tc_id},
        },
        headers=headers,
    )


# --------------------------------------------------------------------------- #
# Queueing
# --------------------------------------------------------------------------- #

def test_queue_against_a_stored_case(client, auth_headers, program_id):
    tc_id = _store_case(client, auth_headers, program_id)
    res = _queue(client, auth_headers, program_id, tc_id)
    assert res.status_code == 200, res.text
    assert res.json()["tool_type"] == "vardrgate_api_test"
    # Only the reference is stored — the spec is not copied into the job.
    assert res.json()["config"] == {"test_case_id": tc_id}


def test_queue_without_a_test_case_id_is_rejected(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/jobs",
        json={"tool_type": "vardrgate_api_test", "target_source": "scope", "config": {}},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "test_case_id" in res.text


def test_queue_with_an_unknown_case_returns_404(client, auth_headers, program_id):
    res = _queue(client, auth_headers, program_id, "no-such-case")
    assert res.status_code == 404


def test_cannot_borrow_a_case_from_another_engagement(client, auth_headers, program_id):
    """The reference must not become a way to pull another engagement's case in."""
    other = client.post("/programs", json={"name": "Other"}, headers=auth_headers).json()["id"]
    foreign = _store_case(client, auth_headers, other)
    try:
        assert _queue(client, auth_headers, program_id, foreign).status_code == 404
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)


def test_unknown_config_keys_are_still_rejected(client, auth_headers, program_id):
    tc_id = _store_case(client, auth_headers, program_id)
    res = client.post(
        f"/programs/{program_id}/jobs",
        json={
            "tool_type": "vardrgate_api_test",
            "target_source": "scope",
            "config": {"test_case_id": tc_id, "severity": "high"},
        },
        headers=auth_headers,
    )
    assert res.status_code == 400


# --------------------------------------------------------------------------- #
# Spec inlining at hand-off — what removes the need for a VardrRunner release
# --------------------------------------------------------------------------- #

def test_pending_inlines_the_stored_spec(client, auth_headers, program_id):
    tc_id = _store_case(client, auth_headers, program_id)
    job_id = _queue(client, auth_headers, program_id, tc_id).json()["id"]

    jobs = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    job = next(j for j in jobs if j["id"] == job_id)

    # VardrGateConfig.from_dict requires test_case as an object.
    assert job["config"]["test_case"]["id"] == "bola-check"
    assert job["config"]["test_case"]["request"]["method"] == "GET"
    assert len(job["config"]["test_case"]["identities"]) == 2
    # The reference is still there alongside it.
    assert job["config"]["test_case_id"] == tc_id


def test_inlining_does_not_write_the_spec_back_to_the_job(client, auth_headers, program_id):
    """The expansion must live only in the response. Persisting it would defeat
    referencing: the job would carry a stale copy of a case that can be edited."""
    tc_id = _store_case(client, auth_headers, program_id)
    job_id = _queue(client, auth_headers, program_id, tc_id).json()["id"]
    client.get("/jobs/pending", headers=auth_headers)

    db = SessionLocal()
    try:
        stored = db.query(ScanJob).filter(ScanJob.id == job_id).first().config
    finally:
        db.close()
    assert stored == {"test_case_id": tc_id}, "spec must not be persisted onto the job"


def test_editing_a_case_changes_what_the_runner_receives(client, auth_headers, program_id):
    """The point of referencing rather than copying."""
    tc_id = _store_case(client, auth_headers, program_id)
    job_id = _queue(client, auth_headers, program_id, tc_id).json()["id"]

    revised = _spec("bola-check-v2")
    revised["request"]["url"] = "https://api.example.com/users/99/profile"
    client.patch(
        f"/programs/{program_id}/test-cases/{tc_id}",
        json={"spec": revised},
        headers=auth_headers,
    )

    jobs = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    job = next(j for j in jobs if j["id"] == job_id)
    assert job["config"]["test_case"]["request"]["url"].endswith("/99/profile")


def test_a_job_whose_case_was_deleted_is_auto_failed(client, auth_headers, program_id):
    """It can never succeed; leaving it pending would hang the queue."""
    tc_id = _store_case(client, auth_headers, program_id)
    job_id = _queue(client, auth_headers, program_id, tc_id).json()["id"]
    client.delete(f"/programs/{program_id}/test-cases/{tc_id}", headers=auth_headers)

    jobs = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    assert all(j["id"] != job_id for j in jobs)

    db = SessionLocal()
    try:
        job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
        assert job.status == "failed"
        assert "no longer exists" in (job.error_message or "")
    finally:
        db.close()


def test_other_tools_are_unaffected_by_inlining(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/jobs",
        json={"tool_type": "httpx", "target_source": "scope"},
        headers=auth_headers,
    )
    job_id = res.json()["id"]
    jobs = client.get("/jobs/pending", headers=auth_headers).json()["jobs"]
    job = next(j for j in jobs if j["id"] == job_id)
    assert "test_case" not in job["config"]


# --------------------------------------------------------------------------- #
# Result upload
# --------------------------------------------------------------------------- #

_RESULT = {
    "test_case_id": "bola-check",
    "executions": [
        {"identity_id": "admin", "status_code": 200, "observed_outcome": "allow",
         "duration_ms": 42, "headers": {"Content-Type": "application/json"}},
        {"identity_id": "attacker", "status_code": 200, "observed_outcome": "allow",
         "duration_ms": 39, "headers": {"Content-Type": "application/json"}},
    ],
    "findings": [
        {"category": "potential_bola", "severity": "high", "confidence": "high",
         "identity_id": "attacker", "message": "attacker read another user's profile",
         "evidence": ["expected deny, observed allow (200)"],
         "detected_at": "2026-08-17T10:00:00Z"},
    ],
}


def _upload(client, headers, job_id, payload=None):
    return client.post(f"/jobs/{job_id}/upload", json=payload or _RESULT, headers=headers)


def _queued_job(client, headers, pid) -> str:
    tc_id = _store_case(client, headers, pid)
    return _queue(client, headers, pid, tc_id).json()["id"]


def test_upload_creates_scan_items_and_evidence(client, auth_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    res = _upload(client, auth_headers, job_id)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "job_id": job_id, "scan_items_created": 1, "evidence_created": 2,
        "already_processed": False,
    }


def test_repeated_identical_upload_is_idempotent(client, auth_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    first = _upload(client, auth_headers, job_id)
    second = _upload(client, auth_headers, job_id)
    assert first.status_code == second.status_code == 200
    assert second.json()["already_processed"] is True

    db = SessionLocal()
    try:
        assert db.query(ScanItem).filter(ScanItem.job_id == job_id).count() == 1
        assert db.query(Evidence).filter(
            Evidence.source == "vardrgate", Evidence.program_id == program_id
        ).count() == 2
    finally:
        db.close()


def test_different_second_upload_is_rejected(client, auth_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    assert _upload(client, auth_headers, job_id).status_code == 200
    changed = {**_RESULT, "findings": []}
    assert _upload(client, auth_headers, job_id, changed).status_code == 409


def test_upload_rejects_a_different_test_case_id(client, auth_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    changed = {**_RESULT, "test_case_id": "some-other-case"}
    response = _upload(client, auth_headers, job_id, changed)
    assert response.status_code == 400
    assert "does not match" in response.text


def test_findings_land_as_triageable_scan_items(client, auth_headers, program_id):
    """Reusing scan_items means the existing triage and promote-to-finding flow
    applies, rather than a parallel one just for VardrGate."""
    job_id = _queued_job(client, auth_headers, program_id)
    _upload(client, auth_headers, job_id)

    db = SessionLocal()
    try:
        item = (
            db.query(ScanItem)
            .filter(ScanItem.job_id == job_id, ScanItem.source == "vardrgate")
            .first()
        )
        assert item is not None
        assert item.severity == "high"
        assert item.type == "potential_bola"
        assert item.status == "new"
        # template_id carries the VardrGate case id, the role a nuclei template id plays.
        assert item.template_id == "bola-check"
        # The asset comes from the stored case's request url.
        assert "api.example.com" in item.asset
        assert "attacker" in item.description
    finally:
        db.close()


def test_executions_land_as_hashed_evidence(client, auth_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    _upload(client, auth_headers, job_id)

    db = SessionLocal()
    try:
        # Scoped to this engagement — other tests in this module also write
        # vardrgate evidence, and an unscoped count would depend on run order.
        rows = (
            db.query(Evidence)
            .filter(Evidence.source == "vardrgate", Evidence.program_id == program_id)
            .all()
        )
        assert len(rows) == 2
        for row in rows:
            assert row.kind == "tool_result"
            assert row.redacted is True
            assert len(row.content_hash) == 64
            assert row.sensitivity == "confidential"
    finally:
        db.close()


def test_structural_response_profile_is_preserved_as_evidence(client, auth_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    payload = {
        "test_case_id": "bola-check",
        "executions": [{
            "identity_id": "attacker", "status_code": 200,
            "response_profile": {
                "kind": "json_object", "schema_hash": "abc123",
                "fields": ["id", "email"], "truncated": False,
            },
        }],
        "findings": [],
    }
    assert _upload(client, auth_headers, job_id, payload).status_code == 200
    db = SessionLocal()
    try:
        evidence = db.query(Evidence).filter(
            Evidence.source == "vardrgate", Evidence.program_id == program_id
        ).one()
        assert '"response_profile"' in evidence.body
        assert '"schema_hash": "abc123"' in evidence.body
    finally:
        db.close()


def test_upload_redacts_a_credential_that_slips_through(client, auth_headers, program_id):
    """VardrGate excludes credential values from its own JSON, but a control that
    depends on the sender behaving is not a control."""
    job_id = _queued_job(client, auth_headers, program_id)
    leaky = {
        "test_case_id": "bola-check",
        "executions": [
            {"identity_id": "admin", "status_code": 200,
             "headers": {"Authorization": "Bearer super-secret-token-value"}},
        ],
        "findings": [
            {"category": "potential_bola", "severity": "high",
             "identity_id": "admin", "message": "leaked",
             "evidence": ["Authorization: Bearer super-secret-token-value"]},
        ],
    }
    assert _upload(client, auth_headers, job_id, leaky).status_code == 200

    db = SessionLocal()
    try:
        bodies = " ".join(
            e.body
            for e in db.query(Evidence).filter(
                Evidence.source == "vardrgate", Evidence.program_id == program_id
            )
        )
        descs = " ".join(
            s.description or "" for s in db.query(ScanItem).filter(ScanItem.job_id == job_id)
        )
    finally:
        db.close()
    assert "super-secret-token-value" not in bodies
    assert "super-secret-token-value" not in descs


def test_unknown_severity_falls_back_to_info(client, auth_headers, program_id):
    """An added upstream level must never silently read as critical."""
    job_id = _queued_job(client, auth_headers, program_id)
    payload = {
        "test_case_id": "bola-check",
        "executions": [],
        "findings": [{"category": "x", "severity": "catastrophic", "message": "m"}],
    }
    _upload(client, auth_headers, job_id, payload)
    db = SessionLocal()
    try:
        item = db.query(ScanItem).filter(ScanItem.job_id == job_id).first()
        assert item.severity == "info"
    finally:
        db.close()


def test_upload_to_a_non_vardrgate_job_is_rejected(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/jobs",
        json={"tool_type": "httpx", "target_source": "scope"},
        headers=auth_headers,
    )
    job_id = res.json()["id"]
    bad = _upload(client, auth_headers, job_id)
    assert bad.status_code == 400
    assert "vardrgate" in bad.text


def test_upload_with_no_findings_is_a_clean_pass(client, auth_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    payload = {"test_case_id": "bola-check", "executions": [], "findings": []}
    res = _upload(client, auth_headers, job_id, payload)
    assert res.status_code == 200
    assert res.json()["scan_items_created"] == 0


def test_upload_requires_auth(client, auth_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    assert client.post(f"/jobs/{job_id}/upload", json=_RESULT).status_code == 401


def test_upload_to_another_users_job_is_404(client, auth_headers, other_headers, program_id):
    job_id = _queued_job(client, auth_headers, program_id)
    assert _upload(client, other_headers, job_id).status_code == 404


def test_upload_to_an_unknown_job_is_404(client, auth_headers):
    assert client.post("/jobs/nope/upload", json=_RESULT, headers=auth_headers).status_code == 404
