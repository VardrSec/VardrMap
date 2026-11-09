import json
from copy import deepcopy

import pytest
from assessments import assess, case_hash

from tests.test_vardrgate_jobs import _queue, _spec


def execution(identity="attacker", outcome="deny", code=403, **extra):
    return {
        "identity_id": identity,
        "observed_outcome": outcome,
        "status_code": code,
        **extra,
    }


BASELINE = execution("admin", "allow", 200)


@pytest.mark.parametrize(
    "outcome,code",
    [
        ("server_error", 503),
        ("client_error", 429),
        ("redirect", 302),
        ("not_found", 404),
        ("unknown", 200),
        ("allow", True),
        ("allow", "200"),
        ("allow", 503),
    ],
)
def test_ambiguous_execution_is_not_conclusive(outcome, code):
    a = assess(_spec(), [BASELINE, execution(outcome=outcome, code=code)], 0)
    assert a["status"] == "partial"
    assert a["inconclusive"] == 1
    assert a["candidate_findings"] == 0


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [execution()],
        [execution("admin", "deny", 401), execution()],
        [execution("admin", "error", 0, error="expired"), execution()],
    ],
)
def test_missing_or_failed_baseline_never_reads_as_clean(rows):
    a = assess(_spec(), rows, 0)
    assert a["status"] == "inconclusive"
    assert a["baseline_valid"] is False
    assert a["evaluated"] == 0


def test_conclusive_means_complete_reported_outcomes_even_with_candidates():
    a = assess(_spec(), [BASELINE, execution(outcome="allow", code=200)], 1)
    assert a["status"] == "conclusive"
    assert a["candidate_findings"] == 1
    assert a["evaluated"] == 2


def test_missing_skip_duplicate_and_unknown_identities_are_visible():
    spec = _spec()
    a = assess(spec, [BASELINE], 0)
    assert a["missing"] == 1 and a["status"] == "partial"
    a = assess(spec, [BASELINE, execution(), execution(), execution("foreign")], 0)
    assert a["inconclusive"] == 1 and a["unexpected"] == 1
    spec["expected_access"][1]["decision"] = "skip"
    a = assess(spec, [BASELINE, execution()], 0)
    assert a["skipped"] == 1 and a["status"] == "partial"
    spec["expected_access"].pop()
    assert assess(spec, [BASELINE, execution()], 0)["skipped"] == 1


def test_declared_body_denials_are_understood_without_reinterpreting_the_body():
    spec = _spec()
    spec["deny_when"] = {"json_field": "error"}
    assert assess(spec, [BASELINE, execution(code=200)], 0)["status"] == "conclusive"
    # An undeclared success-shaped denial is not accepted as an authorization result.
    assert assess(_spec(), [BASELINE, execution(code=200)], 0)["status"] == "partial"


def store(client, headers, pid):
    r = client.post(
        f"/engagements/{pid}/test-cases",
        headers=headers,
        json={"name": "ownership", "spec": _spec()},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_claim_snapshot_assessment_and_evidence_provenance(
    client, auth_headers, program_id, other_headers
):
    tc = store(client, auth_headers, program_id)
    job = _queue(client, auth_headers, program_id, tc).json()["id"]
    claimed = client.post(f"/jobs/{job}/claim", headers=auth_headers)
    assert claimed.status_code == 200
    assert claimed.json()["config"]["test_case"] == _spec()
    changed = deepcopy(_spec())
    changed["id"] = "edited-after-claim"
    changed["expected_access"][1]["decision"] = "allow"
    assert (
        client.patch(
            f"/engagements/{program_id}/test-cases/{tc}",
            headers=auth_headers,
            json={"spec": changed},
        ).status_code
        == 200
    )
    payload = {
        "case_hash": case_hash(_spec()),
        "test_case_id": "bola-check",
        "executions": [BASELINE, execution(outcome="server_error", code=503)],
        "provenance": {"runner_version": "0.0.0-test", "tools": {"vardrgate_api_test": {"sha256": "a" * 64, "version": "unknown"}},
                       "basis": "verified", "case_snapshot": {"credential": {"value": "opaque-upload-secret"}}},
        "findings": [],
    }
    assert (
        client.post(
            f"/jobs/{job}/upload", headers=auth_headers, json=payload
        ).status_code
        == 200
    )
    # Lifecycle completion remains independent of the partial assessment.
    response = client.patch(
        f"/jobs/{job}", headers=auth_headers, json={"status": "done"}
    ).json()
    assert (
        response["status"] == "done" and response["assessment"]["status"] == "partial"
    )
    assert response["assessment"]["case_hash"] == case_hash(_spec())
    assert response["assessment"]["identities"][1]["expected_decision"] == "deny"
    evidence = client.get(
        f"/engagements/{program_id}/evidence",
        headers=auth_headers,
        params={"job_id": job, "case_id": tc, "identity_id": "attacker"},
    ).json()
    assert evidence["total"] == 1
    row = evidence["evidence"][0]
    import json
    provenance = json.loads(row["body"])["provenance"]
    assert provenance["runner_version"] == "0.0.0-test"
    assert provenance["basis"] == "runner_reported_not_server_attested"
    assert "opaque-upload-secret" not in row["body"] and "case_snapshot" not in provenance
    assert (row["job_id"], row["case_id"], row["case_ref"], row["identity_id"]) == (
        job,
        tc,
        "bola-check",
        "attacker",
    )
    assert (
        row["expected_decision"] == "deny" and row["observed_outcome"] == "server_error"
    )
    assert (
        client.get(
            f"/engagements/{program_id}/evidence",
            headers=other_headers,
            params={"job_id": job},
        ).status_code
        == 404
    )
    assert (
        client.get(f"/engagements/{program_id}/jobs", headers=other_headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/jobs/{job}/upload", headers=other_headers, json=payload
        ).status_code
        == 404
    )
    assert client.post(
        f"/jobs/{job}/upload", headers=auth_headers, json=payload
    ).json()["already_processed"]
    assert (
        client.get(
            f"/engagements/{program_id}/evidence",
            headers=auth_headers,
            params={"job_id": job},
        ).json()["total"]
        == 2
    )


def test_unclaimed_legacy_upload_records_unknown_instead_of_inventing_snapshot(
    client, auth_headers, program_id
):
    tc = store(client, auth_headers, program_id)
    job = _queue(client, auth_headers, program_id, tc).json()["id"]
    payload = {
        "test_case_id": "bola-check",
        "executions": [BASELINE, execution(), execution("x" * 201)],
        "findings": [],
    }
    assert (
        client.post(
            f"/jobs/{job}/upload", headers=auth_headers, json=payload
        ).status_code
        == 200
    )
    jobs = client.get(f"/engagements/{program_id}/jobs", headers=auth_headers).json()[
        "jobs"
    ]
    a = next(j["assessment"] for j in jobs if j["id"] == job)
    assert a["status"] == "inconclusive" and "case_snapshot_missing" in a["reasons"]
    evidence = client.get(
        f"/engagements/{program_id}/evidence",
        headers=auth_headers,
        params={"job_id": job},
    ).json()["evidence"]
    long_identity = next(e for e in evidence if e["identity_id"] is None)
    assert json.loads(long_identity["body"])["identity_id"] == "x" * 201


def test_legacy_or_mismatched_result_cannot_establish_case_binding(
    client, auth_headers, program_id
):
    tc = store(client, auth_headers, program_id)
    job = _queue(client, auth_headers, program_id, tc).json()["id"]
    client.post(f"/jobs/{job}/claim", headers=auth_headers)
    payload = {
        "test_case_id": "bola-check",
        "executions": [BASELINE, execution()],
        "findings": [],
    }
    assert (
        client.post(
            f"/jobs/{job}/upload",
            headers=auth_headers,
            json={**payload, "case_hash": "0" * 64},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/jobs/{job}/upload", headers=auth_headers, json=payload
        ).status_code
        == 200
    )
    a = client.patch(
        f"/jobs/{job}", headers=auth_headers, json={"status": "done"}
    ).json()["assessment"]
    assert a["status"] == "inconclusive" and not a["case_snapshot_verified"]
    assert "case_snapshot_unverified" in a["reasons"]


def test_provenance_survives_linking_and_is_snapshotted_in_retest(
    client, auth_headers, program_id
):
    tc = store(client, auth_headers, program_id)
    job = _queue(client, auth_headers, program_id, tc).json()["id"]
    client.post(f"/jobs/{job}/claim", headers=auth_headers)
    client.post(
        f"/jobs/{job}/upload",
        headers=auth_headers,
        json={
            "case_hash": case_hash(_spec()),
            "test_case_id": "bola-check",
            "executions": [BASELINE, execution()],
            "findings": [],
        },
    )
    e = client.get(
        f"/engagements/{program_id}/evidence",
        headers=auth_headers,
        params={"job_id": job, "identity_id": "attacker"},
    ).json()["evidence"][0]
    f = client.post(
        f"/engagements/{program_id}/findings",
        headers=auth_headers,
        json={"title": "Verified ownership issue", "severity": "high"},
    ).json()["id"]
    linked = client.post(
        f"/engagements/{program_id}/evidence/{e['id']}/link",
        headers=auth_headers,
        json={"finding_id": f},
    )
    assert linked.status_code == 200 and linked.json()["job_id"] == job
    r = client.post(
        f"/engagements/{program_id}/findings/{f}/activity",
        headers=auth_headers,
        json={
            "kind": "retest",
            "outcome": "verified_fixed",
            "notes": "Reviewed known baseline and denied caller",
            "evidence_ids": [e["id"]],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["evidence"][0]["identity_id"] == "attacker"
    assert r.json()["evidence"][0]["job_id"] == job
    report = client.post(
        f"/engagements/{program_id}/deliverables",
        headers=auth_headers,
        json={
            "title": "Client assessment",
            "finding_ids": [f],
            "evidence_ids": [e["id"]],
        },
    )
    assert report.status_code == 201, report.text
    assert report.json()["snapshot"]["evidence"][0]["job_id"] == job
    snapshot = report.json()["snapshot"]
    assert snapshot["evidence"][0]["created_at"] == e["created_at"]
    context = snapshot["jobs"][0]
    assert context["job_id"] == job and context["status"] == "running"
    assert context["started_at"] and context["completed_at"] is None
    assert context["case_hash"] == case_hash(_spec())
    assert context["case_snapshot"]["request"]["url"] == _spec()["request"]["url"]
    assert context["snapshot_kind"] == "redacted_unresolved_reviewed"
    assert context["reported_provenance"][0]["runner_version"] == "unknown"
    assert context["reported_provenance"][0]["basis"] == "runner_reported_not_server_attested"
    import redaction
    hostile = {"request": {"method": "GET", "url": "https://user:opaque-userinfo@example.test/path?custom=opaque-query",
                           "headers": {"X-Custom": "opaque-header"}, "body": {"custom": "opaque-body"}},
               "identities": [{"id": "owner", "credential": {"type": "static_header", "value": "opaque-value"}}]}
    projected = redaction.case_snapshot(hostile)
    assert not any(value in str(projected) for value in ("opaque-userinfo", "opaque-query", "opaque-header", "opaque-body", "opaque-value"))
    assert projected["logical_target"] == "https://example.test/path"
    assert projected["case_snapshot"]["identities"][0]["id"] == "owner"
    assert projected["requires_operator_inputs"] and projected["requires_new_review"]
    anonymous = redaction.case_snapshot({"identities": [{"id": "anonymous", "credential": {
        "type": "static_header", "header": "", "value": "", "value_env": None, "value_keychain": ""}}]})
    assert anonymous["requires_operator_inputs"] is False
    assert anonymous["case_snapshot"]["identities"][0]["credential"] == {"type": "static_header"}
    userinfo = redaction.case_snapshot({"request": {"url": "https://user:opaque-only@example.test/path"}})
    assert userinfo["requires_operator_inputs"] and userinfo["logical_target"] == "https://example.test/path"
    assert "opaque-only" not in str(userinfo)
    assert f"Job: {job}" in report.json()["markdown"]
