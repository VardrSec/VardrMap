"""Reviewed session checks retain diagnostics without inventing authorization."""

import pytest
from assessments import assess, case_hash

from tests.test_api_assessments import BASELINE, execution
from tests.test_vardrgate_jobs import _queue, _spec


def spec():
    value = _spec()
    value["identities"][0]["preflight"] = {
        "url": "https://api.example.com/session",
        "expected_status": 200,
        "json_fields": {"user.id": "reviewed-admin", "tenant": "tenant-a"},
    }
    return value


def report(status="passed", reason="identity_verified", code=200):
    return {
        "identity_id": "admin",
        "status": status,
        "reason": reason,
        "status_code": code,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"url": "https://elsewhere.test/session"},
        {"url": "/session"},
        {"url": "https://secret@api.example.com/session"},
        {"url": "https://api.example.com/session#secret"},
        {"url": "https://api.example.com/session?token={{token}}"},
        {"expected_status": True},
        {"expected_status": 401},
        {"json_fields": {}},
        {"json_fields": {"user..id": "x"}},
        {"json_fields": {"id": []}},
        {"json_fields": {"id": " "}},
        {"json_fields": {"id": "é" * 101}},
        {"headers": {"Authorization": "secret"}},
    ],
)
def test_invalid_session_check_is_rejected_on_save(
    client, auth_headers, program_id, change
):
    value = spec()
    value["identities"][0]["preflight"].update(change)
    r = client.post(
        f"/engagements/{program_id}/test-cases",
        headers=auth_headers,
        json={"name": "Session", "spec": value},
    )
    assert r.status_code == 400, r.text


def test_anonymous_preflight_is_rejected(client, auth_headers, program_id):
    value = spec()
    value["identities"][0]["credential"] = {"type": "static_header"}
    assert (
        client.post(
            f"/engagements/{program_id}/test-cases",
            headers=auth_headers,
            json={"name": "Session", "spec": value},
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [report(code=201)],
        [report(), report()],
        [report("failed", "credential_rejected", 401)],
        [{**report(), "identity_id": "other"}],
    ],
)
def test_missing_failed_or_contradictory_preflight_cannot_establish_assessment(rows):
    a = assess(spec(), [BASELINE, execution()], 0, preflight=rows)
    assert a["status"] == "inconclusive"
    assert not a["baseline_valid"]
    assert all(
        i["reason"] == "identity_preflight_not_established" for i in a["identities"]
    )


def test_preflight_success_is_separate_from_authorization():
    a = assess(spec(), [BASELINE, execution()], 0, preflight=[report()])
    assert a["status"] == "conclusive" and a["preflight"]["status"] == "passed"
    assert assess(spec(), [], 0, preflight=[report()])["status"] == "inconclusive"
    assert (
        assess(
            spec(),
            [BASELINE, execution()],
            0,
            preflight=[report()],
            case_verified=False,
        )["preflight"]["status"]
        == "inconclusive"
    )
    assert (
        assess(_spec(), [BASELINE, execution()], 0)["preflight"]["status"]
        == "not_configured"
    )


def test_session_diagnostics_are_bound_persisted_redacted_and_replayable(
    client, auth_headers, program_id, other_headers
):
    value = spec()
    tc = client.post(
        f"/engagements/{program_id}/test-cases",
        headers=auth_headers,
        json={"name": "Session", "spec": value},
    ).json()["id"]
    job = _queue(client, auth_headers, program_id, tc).json()["id"]
    assert client.post(f"/jobs/{job}/claim", headers=auth_headers).status_code == 200
    payload = {
        "test_case_id": value["id"],
        "case_hash": case_hash(value),
        "executions": [],
        "findings": [],
        "preflight": [
            {
                **report("failed", "credential_rejected", 401),
                "body": "raw-session-secret",
                "headers": {"Set-Cookie": "secret-cookie"},
            }
        ],
    }
    assert (
        client.post(
            f"/jobs/{job}/upload", headers=other_headers, json=payload
        ).status_code
        == 404
    )
    first = client.post(f"/jobs/{job}/upload", headers=auth_headers, json=payload)
    assert first.status_code == 200, first.text
    assert (
        first.json()["evidence_created"] == 1
        and first.json()["scan_items_created"] == 0
    )
    assert client.post(
        f"/jobs/{job}/upload", headers=auth_headers, json=payload
    ).json()["already_processed"]
    jobs = client.get(f"/engagements/{program_id}/jobs", headers=auth_headers).json()[
        "jobs"
    ]
    a = next(j for j in jobs if j["id"] == job)["assessment"]
    assert a["status"] == "inconclusive" and a["preflight"]["status"] == "failed"
    evidence = client.get(
        f"/engagements/{program_id}/evidence?job_id={job}", headers=auth_headers
    ).json()["evidence"][0]
    assert (
        evidence["job_id"] == job
        and evidence["case_id"] == tc
        and evidence["identity_id"] == "admin"
    )
    assert evidence["expected_decision"] == evidence["observed_outcome"] == "unknown"
    assert (
        "identity_preflight" in evidence["body"]
        and "credential_rejected" in evidence["body"]
    )
    assert (
        "raw-session-secret" not in evidence["body"]
        and "secret-cookie" not in evidence["body"]
    )


def test_preflight_survives_reviewed_case_save_and_claim(
    client, auth_headers, program_id
):
    value = spec()
    r = client.post(
        f"/engagements/{program_id}/test-cases/reviewed",
        headers=auth_headers,
        json={"reviewed": True, "cases": [{"name": "Reviewed session", "spec": value}]},
    )
    assert r.status_code == 201, r.text
    tc = r.json()["test_cases"][0]["id"]
    job = _queue(client, auth_headers, program_id, tc).json()["id"]
    claimed = client.post(f"/jobs/{job}/claim", headers=auth_headers).json()
    assert claimed["config"]["test_case"] == value
