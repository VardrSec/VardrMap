"""Bound, value-free Gate conclusions; never independent vulnerability verification."""

REASONS = {
    "status_only",
    "ambiguous_http_outcome",
    "execution_error",
    "no_expectation",
    "explicit_skip",
    "assertion_matched",
    "no_assertion_matched",
    "conflicting_assertions",
    "invalid_or_unsupported_json",
    "credential_rejected",
    "state_changed",
    "state_unchanged",
    "verifier_read_failed",
    "verifier_denied",
    "verifier_value_unavailable",
    "verifier_baseline_missing",
    "state_changing_concurrently",
    "target_value_already_present",
    "state_changed_unexpectedly",
    "verifier_unexpected_status",
    "write_execution_error",
    "no_positive_control",
    "positive_control_failed",
    "write_completion_unconfirmed",
    "write_environment_unverified",
    "verifier_reset_failed",
    "identity_preflight_failed",
}
CREDENTIALS = {
    "anonymous_identity",
    "not_checked",
    "preflight_passed",
    "preflight_failed",
    "preflight_passed_resource_401",
    "resource_401_unverified",
}
WRITES = {
    "not_configured",
    "not_applied",
    "inconclusive",
    "verified_effect",
    "verified_no_effect",
}


def enum_value(value, allowed, fallback):
    return value if isinstance(value, str) and value in allowed else fallback


def safe_identity(value):
    return value if isinstance(value, str) and 0 < len(value) <= 200 else ""


def safe_semantic_row(row: dict) -> dict:
    """Drop undeclared metadata and all free-form response/evidence values."""
    out = {
        "identity_id": safe_identity(row.get("identity_id")),
        "expected_access": enum_value(
            row.get("expected_access"), {"allow", "deny", "skip"}, "unknown"
        ),
        "decision": enum_value(
            row.get("decision"),
            {"allowed", "denied", "inconclusive", "skipped"},
            "inconclusive",
        ),
        "source": enum_value(
            row.get("source"),
            {"none", "http_status", "response_assertion", "write_verification"},
            "none",
        ),
        "reason": enum_value(
            row.get("reason"), REASONS, "unrecognized_assessment_reason"
        ),
        "credential_status": enum_value(
            row.get("credential_status"), CREDENTIALS, "not_recorded"
        ),
        "write_verification": enum_value(
            row.get("write_verification"), WRITES, "not_recorded"
        ),
        "matched_assertions": row.get("matched_assertions", [])
        if isinstance(row.get("matched_assertions", []), list)
        and len(row.get("matched_assertions", [])) <= 32
        and all(
            type(i) is int and 0 <= i < 32 for i in row.get("matched_assertions", [])
        )
        else [],
    }
    index = row.get("execution_index")
    if type(index) is int and 0 <= index < 100:
        out["execution_index"] = index
    v = row.get("verification")
    if isinstance(v, dict):
        statuses = v.get("before_statuses")
        out["verification"] = {
            "strategy": enum_value(
                v.get("strategy"),
                {"changed", "created", "deleted", "legacy_change"},
                "unknown",
            ),
            "environment": enum_value(
                v.get("environment"),
                {"unknown", "synchronous_isolated", "legacy"},
                "unknown",
            ),
            "reader_identity_id": safe_identity(v.get("reader_identity_id")),
            "reader_credential_status": enum_value(
                v.get("reader_credential_status"), CREDENTIALS, "not_recorded"
            ),
            "before_statuses": statuses
            if isinstance(statuses, list)
            and len(statuses) <= 2
            and all(type(s) is int and 0 <= s <= 599 for s in statuses)
            else [],
            "after_status": v.get("after_status")
            if type(v.get("after_status")) is int and 0 <= v["after_status"] <= 599
            else 0,
            "reset_status": v.get("reset_status")
            if type(v.get("reset_status")) is int and 0 <= v["reset_status"] <= 599
            else 0,
        }
    return out


def apply_semantics(
    spec: dict,
    identities: list[dict],
    executions: list[dict],
    semantic: list[dict],
    verified: bool,
) -> None:
    for item in identities:
        identity = item["identity_id"]
        rows = [r for r in semantic if r["identity_id"] == identity]
        expectations = [
            r
            for r in spec.get("expected_access", [])
            if r.get("identity_id") == identity
        ]
        configured = expectations[0] if len(expectations) == 1 else {}
        protected = bool(
            configured.get("response_assertions") or spec.get("write_verification")
        )
        if not rows:
            if protected and item["state"] != "skipped":
                item.update(state="inconclusive", reason="semantic_assessment_missing")
            continue
        if len(rows) != 1 or rows[0]["expected_access"] != item["expected_decision"]:
            item.update(state="inconclusive", reason="semantic_assessment_inconsistent")
            continue
        row = rows[0]
        item.update(
            reported_decision=row["decision"],
            source=row["source"],
            credential_status=row["credential_status"],
            write_verification=row["write_verification"],
            matched_assertions=row["matched_assertions"],
        )
        oracle = (
            spec.get("write_verification")
            if isinstance(spec.get("write_verification"), dict)
            else {}
        )
        reader = (
            oracle.get("identity") if isinstance(oracle.get("identity"), dict) else {}
        )
        if "verification" in row and row["verification"][
            "reader_identity_id"
        ] == reader.get("id"):
            item["verification"] = row["verification"]
        if item["state"] == "skipped":
            continue
        if not verified:
            item.update(state="inconclusive", reason="case_snapshot_unverified")
            continue
        if row["decision"] not in {"allowed", "denied"}:
            item.update(state="inconclusive", reason=row["reason"])
            continue
        actual = [e for e in executions if e.get("identity_id") == identity]
        if len(actual) != 1 or (
            "execution_index" in row
            and (
                row["execution_index"] >= len(executions)
                or executions[row["execution_index"]].get("identity_id") != identity
            )
        ):
            item.update(state="inconclusive", reason="semantic_assessment_inconsistent")
            continue
        decision = "allow" if row["decision"] == "allowed" else "deny"
        valid = False
        if (
            row["source"] == "response_assertion"
            and not actual[0].get("error")
            and not actual[0].get("error_kind")
            and type(actual[0].get("status_code")) is int
            and 100 <= actual[0]["status_code"] <= 599
        ):
            rules = configured.get("response_assertions") or []
            indices = row["matched_assertions"]
            valid = (
                isinstance(rules, list)
                and bool(indices)
                and row["reason"] == "assertion_matched"
                and all(
                    i < len(rules)
                    and isinstance(rules[i], dict)
                    and rules[i].get("decision") == decision
                    and (
                        not rules[i].get("status_codes")
                        or actual[0].get("status_code") in rules[i]["status_codes"]
                    )
                    for i in indices
                )
            )
        elif row["source"] == "write_verification":
            oracle = (
                spec.get("write_verification")
                if isinstance(spec.get("write_verification"), dict)
                else {}
            )
            evidence = row.get("verification") or {}
            valid = (
                bool(oracle)
                and evidence.get("reader_identity_id")
                == (oracle.get("identity") or {}).get("id")
                and evidence.get("strategy")
                == (oracle.get("strategy") or "legacy_change")
                and evidence.get("environment")
                == (oracle.get("environment") or "legacy")
                and len(evidence.get("before_statuses", [])) == 2
                and evidence.get("after_status", 0) > 0
                and row["reason"]
                == ("state_changed" if decision == "allow" else "state_unchanged")
            )
            before = evidence.get("before_statuses", [])
            after = evidence.get("after_status", 0)
            valid = (
                valid
                and evidence.get("environment") != "unknown"
                and all(
                    (
                        s == 404
                        if oracle.get("strategy") == "created"
                        else 200 <= s < 300
                    )
                    for s in before
                )
                and (
                    200 <= after < 300
                    or after == 404
                    or after in oracle.get("after_status", [])
                )
            )
            if oracle.get("reset"):
                reset = evidence.get("reset_status", 0)
                valid = valid and 200 <= reset < 300 and reset != 202
            if decision == "deny":
                status = actual[0].get("status_code")
                valid = (
                    valid
                    and not actual[0].get("error")
                    and not actual[0].get("error_kind")
                    and type(status) is int
                    and 100 <= status <= 599
                    and status != 202
                )
        elif row["source"] == "http_status" and not protected:
            valid = (
                item["state"] == "evaluated" and item["observed_outcome"] == decision
            )
        if valid:
            item.update(state="evaluated", reason="reported_" + row["source"])
            if item["expected_decision"] == "allow" and decision != "allow":
                item.update(state="inconclusive", reason="legitimate_baseline_denied")
        else:
            item.update(state="inconclusive", reason="semantic_assessment_inconsistent")
