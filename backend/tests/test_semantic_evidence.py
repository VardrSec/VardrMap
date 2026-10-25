"""Semantic conclusions stay bound to the reviewed case and response provenance."""

import json
from assessments import assess, case_hash
from assessment_evidence import safe_semantic_row
from tests.test_api_assessments import BASELINE, execution, store
from tests.test_vardrgate_jobs import _queue, _spec


def row(identity="attacker", expected="deny", decision="inconclusive", **extra):
    return {
        "identity_id": identity,
        "expected_access": expected,
        "decision": decision,
        "source": "response_assertion",
        "reason": "no_assertion_matched",
        "credential_status": "not_checked",
        "write_verification": "not_configured",
        **extra,
    }


def semantic_spec():
    spec = _spec()
    spec["expected_access"][1]["response_assertions"] = [
        {"json_pointer": "/error", "equals": "PRIVATE", "decision": "deny"},
        {"json_pointer": "/private", "equals": "value", "decision": "allow"},
    ]
    return spec


def test_semantics_prevent_raw_success_from_becoming_a_pass():
    a = assess(
        semantic_spec(),
        [BASELINE, execution(outcome="allow", code=200)],
        0,
        semantic=[row()],
    )
    peer = a["identities"][1]
    assert peer["state"] == "inconclusive" and peer["reason"] == "no_assertion_matched"
    assert (
        peer["observed_outcome"] == "allow"
        and peer["reported_decision"] == "inconclusive"
    )


def test_bound_assertion_and_raw_http_are_separate():
    a = assess(
        semantic_spec(),
        [BASELINE, execution(outcome="allow", code=200)],
        0,
        semantic=[
            row(decision="denied", reason="assertion_matched", matched_assertions=[0])
        ],
    )
    assert a["identities"][1]["state"] == "evaluated"
    assert a["identities"][1]["reported_decision"] == "denied"
    assert a["identities"][1]["observed_outcome"] == "allow"
    for code in (0, True, "200"):
        invalid = assess(
            semantic_spec(),
            [BASELINE, execution(code=code)],
            0,
            semantic=[
                row(
                    decision="denied",
                    reason="assertion_matched",
                    matched_assertions=[0],
                )
            ],
        )
        assert invalid["identities"][1]["state"] == "inconclusive"
    for indices in ([1], [99], [0, 999], [True]):
        a = assess(
            semantic_spec(),
            [BASELINE, execution()],
            0,
            semantic=[
                row(
                    decision="denied",
                    reason="assertion_matched",
                    matched_assertions=indices,
                )
            ],
        )
        assert a["identities"][1]["state"] == "inconclusive"


def test_unbound_duplicate_and_missing_proof_are_unknown():
    spec = semantic_spec()
    good = row(decision="denied", reason="assertion_matched", matched_assertions=[0])
    assert (
        assess(spec, [BASELINE, execution()], 0, case_verified=False, semantic=[good])[
            "status"
        ]
        == "inconclusive"
    )
    assert (
        assess(spec, [BASELINE, execution()], 0, semantic=[good, good])["identities"][
            1
        ]["state"]
        == "inconclusive"
    )
    assert (
        assess(spec, [BASELINE, execution()], 0)["identities"][1]["reason"]
        == "semantic_assessment_missing"
    )
    assert (
        assess(_spec(), [BASELINE, execution(code=401)], 0)["identities"][1]["reason"]
        == "credential_rejected"
    )


def test_malformed_reviewed_constraints_cannot_establish_a_result():
    for codes in (None, 404, "404", {}, [True]):
        spec = semantic_spec()
        spec["expected_access"][1]["response_assertions"][0]["status_codes"] = codes
        proof = row(
            decision="denied", reason="assertion_matched", matched_assertions=[0]
        )
        result = assess(spec, [BASELINE, execution()], 0, semantic=[proof])
        assert result["identities"][1]["state"] == "inconclusive"


def test_unknown_metadata_and_observed_values_are_dropped():
    value = row(
        reason="response-secret",
        source={},
        matched_assertions=[0, 999],
        body="private-body",
        verification={
            "before_statuses": [200, 200, 500],
            "strategy": "changed",
            "value": "private-value",
        },
    )
    safe = safe_semantic_row(value)
    assert (
        safe["reason"] == "unrecognized_assessment_reason"
        and safe["matched_assertions"] == []
    )
    assert safe["verification"]["before_statuses"] == []
    assert "private" not in json.dumps(safe) and "response-secret" not in json.dumps(
        safe
    )


def test_verifier_interruption_reasons_remain_inconclusive():
    for reason in ("execution_cancelled", "reset_baseline_mismatch"):
        result = assess(
            semantic_spec(),
            [BASELINE, execution()],
            0,
            semantic=[row(reason=reason, source="write_verification")],
        )
        assert result["identities"][1]["state"] == "inconclusive"
        assert result["identities"][1]["reason"] == reason


def test_write_readback_requires_bound_provenance_and_a_control():
    spec = _spec()
    spec["write_verification"] = {
        "identity": {"id": "reader"},
        "strategy": "changed",
        "environment": "synchronous_isolated",
        "json_pointer": "/value",
        "changed_to": "target",
    }
    proof = {
        "strategy": "changed",
        "environment": "synchronous_isolated",
        "reader_identity_id": "reader",
        "reader_credential_status": "not_checked",
        "before_statuses": [200, 200],
        "after_status": 200,
    }
    control = row(
        "admin",
        "allow",
        "allowed",
        source="write_verification",
        reason="state_changed",
        verification=proof,
    )
    peer = row(
        decision="denied",
        source="write_verification",
        reason="state_unchanged",
        verification=proof,
    )
    a = assess(
        spec,
        [BASELINE, execution(outcome="allow", code=204)],
        0,
        semantic=[control, peer],
    )
    assert a["status"] == "conclusive" and a["baseline_valid"]
    assert a["identities"][1]["credential_status"] == "not_checked"
    for change in (
        {"before_statuses": [0, 0]},
        {"after_status": 0},
        {"reader_identity_id": "foreign"},
        {"environment": "unknown"},
    ):
        bad = {**peer, "verification": {**proof, **change}}
        assert (
            assess(spec, [BASELINE, execution()], 0, semantic=[control, bad])[
                "identities"
            ][1]["state"]
            == "inconclusive"
        )
    assert (
        assess(spec, [BASELINE, execution(code=202)], 0, semantic=[control, peer])[
            "identities"
        ][1]["state"]
        == "inconclusive"
    )


def test_upload_retains_semantics_in_redacted_evidence_and_receipt(
    client, auth_headers, program_id
):
    tc = store(client, auth_headers, program_id)
    job = _queue(client, auth_headers, program_id, tc).json()["id"]
    client.post(f"/jobs/{job}/claim", headers=auth_headers)
    payload = {
        "case_hash": case_hash(_spec()),
        "executions": [BASELINE, execution()],
        "findings": [],
        "assessments": [
            row(
                source="http_status",
                reason="status_only",
                decision="denied",
                body="never-retain-this",
            )
        ],
    }
    upload = client.post(f"/jobs/{job}/upload", headers=auth_headers, json=payload)
    assert upload.status_code == 200, upload.text
    replay = client.post(f"/jobs/{job}/upload", headers=auth_headers, json=payload)
    assert replay.json()["already_processed"] is True
    evidence = client.get(
        f"/engagements/{program_id}/evidence",
        headers=auth_headers,
        params={"job_id": job, "identity_id": "attacker"},
    ).json()["evidence"][0]
    assert (
        "scanner_assessments" in evidence["body"]
        and "never-retain-this" not in evidence["body"]
    )


def test_legacy_receipt_replay_remains_a_noop(client, auth_headers, program_id):
    tc = store(client, auth_headers, program_id)
    job = _queue(client, auth_headers, program_id, tc).json()["id"]
    client.post(f"/jobs/{job}/claim", headers=auth_headers)
    payload = {
        "case_hash": case_hash(_spec()),
        "executions": [BASELINE, execution()],
        "findings": [],
    }
    assert (
        client.post(
            f"/jobs/{job}/upload", headers=auth_headers, json=payload
        ).status_code
        == 200
    )
    payload["assessments"] = [row()]
    result = client.post(f"/jobs/{job}/upload", headers=auth_headers, json=payload)
    assert result.status_code == 200 and result.json()["already_processed"] is True
