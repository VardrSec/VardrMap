"""Interpret reported Gate executions without equating completion with assurance."""

import hashlib
import json
from collections import defaultdict
from assessment_evidence import apply_semantics, safe_semantic_row


def case_hash(spec: dict) -> str:
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def assess(
    spec: dict | None,
    executions: list[dict],
    candidate_count: int,
    *,
    case_verified: bool = True,
    preflight: list[dict] | None = None,
    semantic: list[dict] | None = None,
) -> dict:
    """Derive completeness against the spec captured at claim, never from findings count.

    This summarizes runner-reported outcomes. It does not independently verify
    permission, business impact, response bodies or methodology coverage.
    """
    spec = spec or {}
    session = assess_preflight(spec, preflight or [], case_verified)
    expected = defaultdict(list)
    for item in spec.get("expected_access", []):
        expected[item["identity_id"]].append(item["decision"])
    reported = defaultdict(list)
    for item in executions:
        reported[str(item.get("identity_id") or "")].append(item)
    identities = []
    for identity in spec.get("identities", []):
        identity_id = identity["id"]
        decisions = expected[identity_id]
        decision = decisions[0] if len(decisions) == 1 else "unknown"
        rows = reported.get(identity_id, [])
        outcome = (
            str(rows[0].get("observed_outcome") or "unknown")
            if len(rows) == 1
            else "unknown"
        )
        state = "inconclusive"
        reason = "ambiguous_response"
        if decision in {"skip", "unknown"}:
            state, reason = "skipped", "no_reviewed_expectation"
        elif not rows:
            state, reason = "missing", "execution_missing"
        elif len(rows) != 1:
            reason = "duplicate_execution"
        else:
            row = rows[0]
            code = row.get("status_code")
            valid_code = type(code) is int and 100 <= code <= 599
            allow = valid_code and 200 <= code < 300 and outcome == "allow"
            deny = (
                valid_code
                and outcome == "deny"
                and (
                    code in {401, 403}
                    or code in spec.get("deny_status", [])
                    or (200 <= code < 300 and bool(spec.get("deny_when")))
                )
            )
            if row.get("error") or row.get("error_kind") or not (allow or deny):
                reason = (
                    "execution_error"
                    if row.get("error") or row.get("error_kind")
                    else "ambiguous_response"
                )
            elif decision == "allow" and not allow:
                reason = "legitimate_baseline_denied"
            else:
                state, reason = "evaluated", "reported_allow_or_deny"
        identities.append(
            {
                "identity_id": identity_id,
                "expected_decision": decision,
                "observed_outcome": outcome,
                "state": state,
                "reason": reason,
            }
        )
    apply_semantics(spec, identities, executions, [safe_semantic_row(r) for r in semantic or []], case_verified)
    for item in identities:
        declared = next((i for i in spec.get("identities", []) if i["id"] == item["identity_id"]), {})
        credential = declared.get("credential") or {}
        rows = reported.get(item["identity_id"], [])
        sends_credentials = credential.get("type") in {"bearer", "api_key_header"} or (credential.get("type") == "static_header" and bool(credential.get("header")))
        checked = next((p for p in session["identities"] if p["identity_id"] == item["identity_id"]), None)
        credential_status = "not_checked" if sends_credentials else "anonymous_identity"
        if checked:
            credential_status = "preflight_passed" if checked["status"] == "passed" else "preflight_failed"
        if sends_credentials and len(rows) == 1 and rows[0].get("status_code") == 401:
            credential_status = "preflight_passed_resource_401" if credential_status == "preflight_passed" else "resource_401_unverified"
        item["credential_status"] = credential_status if case_verified else "not_recorded"
        verification = item.get("verification")
        if verification:
            oracle = spec.get("write_verification") or {}
            reader = oracle.get("identity") or {}
            credential = reader.get("credential") or {}
            reader_status = "anonymous_identity" if credential.get("type") == "static_header" and not credential.get("header") else "not_checked"
            checked = next((p for p in session["identities"] if p["identity_id"] == reader.get("id")), None)
            if checked:
                reader_status = "preflight_passed" if checked["status"] == "passed" else "preflight_failed"
            verification["reader_credential_status"] = reader_status if case_verified else "not_recorded"
        if item["expected_decision"] == "deny" and len(rows) == 1 and rows[0].get("status_code") == 401 and sends_credentials and not spec.get("unauthorized_is_denial") and item.get("reported_decision") != "allowed":
            item.update(state="inconclusive", reason="credential_rejected")
    if not case_verified:
        for item in identities:
            if item["state"] == "evaluated":
                item.update(state="inconclusive", reason="case_snapshot_unverified")
    if session["status"] not in {"passed", "not_configured"}:
        for item in identities:
            if item["state"] != "skipped":
                item.update(
                    state="inconclusive", reason="identity_preflight_not_established"
                )
    baseline = case_verified and any(
        i["expected_decision"] == "allow" and i["state"] == "evaluated"
        for i in identities
    )
    # A denied caller's response cannot establish authorization without a working
    # legitimate baseline. Preserve candidates, but do not call this conclusive.
    if not baseline:
        for item in identities:
            if item["state"] == "evaluated":
                item.update(state="inconclusive", reason="legitimate_baseline_missing")
    counts = {
        state: sum(i["state"] == state for i in identities)
        for state in ("evaluated", "inconclusive", "missing", "skipped")
    }
    unexpected = sum(
        len(rows)
        for identity, rows in reported.items()
        if identity not in {i["identity_id"] for i in identities}
    )
    complete = (
        bool(identities) and counts["evaluated"] == len(identities) and unexpected == 0
    )
    status = (
        "conclusive"
        if complete
        else "partial"
        if counts["evaluated"]
        else "inconclusive"
    )
    reasons = sorted({i["reason"] for i in identities if i["state"] != "evaluated"})
    if not baseline:
        reasons.append("legitimate_baseline_missing")
    if unexpected:
        reasons.append("unexpected_identity")
    if not spec:
        reasons.append("case_snapshot_missing")
    if not case_verified:
        reasons.append("case_snapshot_unverified")
    return {
        "status": status,
        **counts,
        "unexpected": unexpected,
        "baseline_valid": baseline,
        "candidate_findings": candidate_count,
        "identities": identities,
        "reasons": sorted(set(reasons)),
        "case_hash": case_hash(spec) if spec else None,
        "case_snapshot_verified": bool(spec) and case_verified,
        "preflight": session,
    }


def assess_preflight(spec: dict, rows: list[dict], verified: bool) -> dict:
    declared = {
        i["id"]: i["preflight"]
        for i in spec.get("identities", [])
        if i.get("preflight") is not None
    }
    oracle = spec.get("write_verification") if isinstance(spec.get("write_verification"), dict) else {}
    reader = oracle.get("identity") if isinstance(oracle.get("identity"), dict) else {}
    if reader.get("preflight") is not None:
        declared[reader["id"]] = reader["preflight"]
    reported = defaultdict(list)
    for row in rows:
        reported[str(row.get("identity_id") or "")].append(row)
    identities = []
    for identity, config in declared.items():
        items = reported[identity]
        status, reason, code = "missing", "preflight_missing", None
        if len(items) == 1:
            row = items[0]
            code = row.get("status_code")
            status, reason = "inconclusive", "preflight_inconsistent"
            if (
                row.get("status") == "passed"
                and row.get("reason") == "identity_verified"
                and type(code) is int
                and code == config["expected_status"]
            ):
                status, reason = "passed", "identity_verified"
            elif row.get("status") == "failed" and row.get("reason") in {
                "credential_rejected",
                "identity_mismatch",
                "unexpected_status",
                "execution_error",
            }:
                status, reason = "failed", row["reason"]
        elif items:
            status, reason = "inconclusive", "duplicate_preflight"
        if not verified:
            status, reason = "inconclusive", "case_snapshot_unverified"
        identities.append(
            {
                "identity_id": identity,
                "status": status,
                "reason": reason,
                "status_code": code,
            }
        )
    unexpected = sum(
        len(items) for identity, items in reported.items() if identity not in declared
    )
    status = (
        "not_configured"
        if not declared
        else "passed"
        if all(i["status"] == "passed" for i in identities) and not unexpected
        else "failed"
        if any(i["status"] == "failed" for i in identities)
        else "inconclusive"
    )
    if unexpected:
        status = "inconclusive"
    return {"status": status, "identities": identities, "unexpected": unexpected}
