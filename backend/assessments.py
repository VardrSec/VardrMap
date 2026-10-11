"""Interpret reported Gate executions without equating completion with assurance."""

import hashlib
import json
from collections import defaultdict


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
) -> dict:
    """Derive completeness against the spec captured at claim, never from findings count.

    This summarizes runner-reported outcomes. It does not independently verify
    permission, business impact, response bodies or methodology coverage.
    """
    spec = spec or {}
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
    if not case_verified:
        for item in identities:
            if item["state"] == "evaluated":
                item.update(state="inconclusive", reason="case_snapshot_unverified")
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
    }
