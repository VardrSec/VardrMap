"""Authorization coverage over real stored inventory, cases, jobs, evidence.

Everything here goes through the public API with synthetic data only: no external
target, no real credential. The six identities mirror the researcher's usual cast:
the resource owner, another authenticated user, a user from a different tenant,
an administrator, an anonymous caller and a caller with rejected credentials.
"""
from assessments import case_hash
from db import SessionLocal
from models import ApiEndpoint, AuthorizationTestCase, Evidence, ScanItem, ScanJob

HOST = "https://api.example.com"


def identity(name, credential=None):
    return {"id": name, "credential": credential or {"type": "bearer", "value_env": f"{name.upper().replace('-', '_')}_TOKEN"}}


OWNER, PEER, TENANT_B, ADMIN = (identity(n) for n in ("owner", "peer", "tenant-b", "admin"))
ANONYMOUS = identity("anonymous", {"type": "static_header"})
INVALID = identity("invalid", {"type": "bearer", "value_env": "INVALID_TOKEN"})
CAST = [OWNER, PEER, TENANT_B, ADMIN, ANONYMOUS, INVALID]
EXPECT = {"owner": "allow", "peer": "deny", "tenant-b": "deny", "admin": "allow", "anonymous": "deny", "invalid": "deny"}


def spec(case_id, method, path, people=CAST, expect=EXPECT):
    value = {
        "id": case_id,
        "identities": people,
        "request": {"method": method, "url": f"{HOST}{path}"},
        "expected_access": [{"identity_id": p["id"], "decision": expect[p["id"]]} for p in people],
    }
    if method != "GET":
        value["mutating"] = True  # Gate refuses unsafe methods unless the case says so
    return value


def run(outcome, code, who):
    return {"identity_id": who, "observed_outcome": outcome, "status_code": code}


def clean_run(people=CAST):
    rows = []
    for person in people:
        who = person["id"]
        if EXPECT[who] == "allow":
            rows.append(run("allow", 200, who))
        else:
            rows.append(run("deny", 401 if who == "invalid" else 403, who))
    return rows


def capture(client, headers, pid, method, path, label="owner", body="", status=200):
    res = client.post(
        f"/engagements/{pid}/api/exchanges",
        headers=headers,
        json={"method": method, "url": f"{HOST}{path}", "identity_label": label, "response_status": status, "request_body": body},
    )
    assert res.status_code == 201, res.text


def store(client, headers, pid, case_spec, name="case"):
    res = client.post(f"/engagements/{pid}/test-cases", headers=headers, json={"name": name, "spec": case_spec})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def queue(client, headers, pid, case_id):
    res = client.post(
        f"/engagements/{pid}/jobs",
        headers=headers,
        json={"tool_type": "vardrgate_api_test", "target_source": "scope", "config": {"test_case_id": case_id}},
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def execute(client, headers, pid, case_id, case_spec, executions, findings=()):
    job = queue(client, headers, pid, case_id)
    assert client.post(f"/jobs/{job}/claim", headers=headers).status_code == 200
    body = {
        "case_hash": case_hash(case_spec),
        "test_case_id": case_spec["id"],
        "executions": executions,
        "findings": list(findings),
    }
    assert client.post(f"/jobs/{job}/upload", headers=headers, json=body).status_code == 200
    assert client.patch(f"/jobs/{job}", headers=headers, json={"status": "done"}).status_code == 200
    return job


def coverage(client, headers, pid, **params):
    res = client.get(f"/engagements/{pid}/api/coverage", headers=headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def operation(data, method, path):
    return next(o for o in data["operations"] if o["method"] == method and o["path_template"] == path)


def identity_states(op):
    return {row["identity_id"]: row for row in op["identity_coverage"]}


def build_engagement(client, headers, pid):
    for method, path in [
        ("GET", "/orders/7"),
        ("GET", "/invoices/9"),
        ("GET", "/profile"),
        ("POST", "/orders/7/refund"),
        ("GET", "/reports/3"),
        ("GET", "/exports/11"),
    ]:
        capture(client, headers, pid, method, path)

    orders = spec("orders-bola", "GET", "/orders/42")
    orders_id = store(client, headers, pid, orders, "orders BOLA")
    violating = clean_run()
    violating[1] = run("allow", 200, "peer")  # peer reached an order it should not
    finding = {"category": "potential_bola", "severity": "high", "message": "peer read the owner's order"}
    execute(client, headers, pid, orders_id, orders, violating, [finding])

    invoices = spec("invoices-bola", "GET", "/invoices/55", [OWNER, PEER], EXPECT)
    invoices_id = store(client, headers, pid, invoices, "invoices")
    queue(client, headers, pid, invoices_id)  # queued, never executed

    refund = spec("refund", "POST", "/orders/42/refund", [OWNER, ADMIN], EXPECT)
    refund_id = store(client, headers, pid, refund, "refund")
    execute(client, headers, pid, refund_id, refund, [run("deny", 403, "owner"), run("deny", 403, "admin")])  # no working baseline

    reports = spec("reports", "GET", "/reports/3", [OWNER, PEER, ADMIN], EXPECT)
    reports_id = store(client, headers, pid, reports, "reports")
    execute(client, headers, pid, reports_id, reports, clean_run([OWNER, PEER, ADMIN]))

    exports = spec("exports", "GET", "/exports/11", [OWNER, PEER, ADMIN], EXPECT)
    exports_id = store(client, headers, pid, exports, "exports")
    execute(client, headers, pid, exports_id, exports, [run("allow", 200, "owner"), run("deny", 403, "peer")])

    store(client, headers, pid, spec("elsewhere", "GET", "/never-captured/1", [OWNER, PEER], EXPECT), "elsewhere")
    skipped = spec("skipped", "GET", "/profile", [OWNER], {"owner": "skip"})
    store(client, headers, pid, skipped, "unreviewed")


def test_states_distinguish_what_was_reviewed_executed_and_concluded(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    data = coverage(client, auth_headers, program_id)

    assert operation(data, "GET", "/profile")["state"] == "untested"  # only an all-skip case exists
    assert operation(data, "GET", "/invoices/{id}")["state"] == "reviewed_not_executed"
    assert operation(data, "GET", "/reports/{id}")["state"] == "conclusive"
    assert operation(data, "GET", "/exports/{id}")["state"] == "partial"
    assert operation(data, "GET", "/orders/{id}")["state"] == "violation_candidate"
    refund = operation(data, "POST", "/orders/{id}/refund")
    assert refund["state"] == "inconclusive"  # neither legitimate baseline worked
    assert data["summary"]["total"] == 6
    assert data["summary"]["untested"] == 1 and data["summary"]["conclusive"] == 1


def test_violation_candidate_carries_its_backing_evidence_and_does_not_read_as_clean(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["candidates"]["open"] == 1
    assert op["candidates"]["backing_evidence"] == 1  # reviewed deny observed as allow
    rows = identity_states(op)
    assert rows["peer"]["state"] == "evaluated" and rows["peer"]["expected"] == "deny"
    # A rejected credential is inconclusive, never a verified denial.
    assert rows["invalid"]["state"] == "inconclusive" and rows["invalid"]["reason"] == "credential_rejected"
    assert op["cases"][0]["executed"] and op["cases"][0]["assessment_status"] == "partial"


def test_identity_gaps_are_reported_per_operation(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    data = coverage(client, auth_headers, program_id)
    assert data["identities"] == ["admin", "anonymous", "invalid", "owner", "peer", "tenant-b"]

    reports = identity_states(operation(data, "GET", "/reports/{id}"))
    assert reports["owner"]["state"] == reports["peer"]["state"] == reports["admin"]["state"] == "evaluated"
    for missing in ("tenant-b", "anonymous", "invalid"):
        assert reports[missing]["state"] == "not_reviewed"

    exports = identity_states(operation(data, "GET", "/exports/{id}"))
    assert exports["admin"]["state"] == "missing"  # reviewed, but the run reported no admin result
    invoices = identity_states(operation(data, "GET", "/invoices/{id}"))
    assert invoices["owner"]["state"] == invoices["peer"]["state"] == "reviewed_not_run"
    assert invoices["admin"]["state"] == "not_reviewed"
    untested = identity_states(operation(data, "GET", "/profile"))
    assert {row["state"] for row in untested.values()} == {"not_reviewed"}


def test_inventory_labels_and_unmatched_cases_are_visible(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    capture(client, auth_headers, program_id, "GET", "/orders/8", label="peer")
    data = coverage(client, auth_headers, program_id)
    assert operation(data, "GET", "/orders/{id}")["observed_identities"] == ["owner", "peer"]
    reasons = {row["name"]: row["reason"] for row in data["unmatched_cases"]}
    assert reasons == {"elsewhere": "no_observed_operation", "unreviewed": "no_reviewed_expectation"}


def test_closing_a_candidate_as_a_false_positive_removes_the_flag_but_not_the_history(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    db = SessionLocal()
    try:
        item = db.query(ScanItem).filter(ScanItem.program_id == program_id, ScanItem.source == "vardrgate").one()
        item.status = "false_positive"
        db.commit()
    finally:
        db.close()
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["candidates"] == {"open": 0, "promoted": 0, "false_positive": 1, "backing_evidence": 1}
    assert op["state"] == "partial"  # executed with evaluated results, but not conclusive


def test_a_completed_job_without_an_assessment_is_not_an_execution(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    case_spec = spec("orders", "GET", "/orders/42", [OWNER, PEER], EXPECT)
    case_id = store(client, auth_headers, program_id, case_spec)
    job = queue(client, auth_headers, program_id, case_id)
    assert client.patch(f"/jobs/{job}", headers=auth_headers, json={"status": "failed"}).status_code == 200
    assert operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")["state"] == "reviewed_not_executed"


def test_state_filter_and_paging(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    only = coverage(client, auth_headers, program_id, state="untested")
    assert only["filtered_total"] == 1 and [o["path_template"] for o in only["operations"]] == ["/profile"]
    assert only["summary"]["total"] == 6  # the summary always describes the whole engagement
    page = coverage(client, auth_headers, program_id, limit=2, offset=1)
    assert len(page["operations"]) == 2 and page["filtered_total"] == 6


def test_the_view_is_read_only(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    db = SessionLocal()
    try:
        before = [db.query(m).count() for m in (ApiEndpoint, AuthorizationTestCase, ScanJob, ScanItem, Evidence)]
    finally:
        db.close()
    coverage(client, auth_headers, program_id)
    coverage(client, auth_headers, program_id, state="conclusive")
    db = SessionLocal()
    try:
        after = [db.query(m).count() for m in (ApiEndpoint, AuthorizationTestCase, ScanJob, ScanItem, Evidence)]
    finally:
        db.close()
    assert before == after


def test_other_users_cannot_read_coverage_and_never_see_it_in_their_own(client, auth_headers, other_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    assert client.get(f"/engagements/{program_id}/api/coverage", headers=other_headers).status_code == 404
    assert client.get(f"/engagements/{program_id}/api/coverage").status_code == 401
    mine = client.post("/programs", json={"name": "Other engagement"}, headers=other_headers).json()["id"]
    try:
        theirs = coverage(client, other_headers, mine)
        assert theirs["operations"] == [] and theirs["identities"] == [] and theirs["unmatched_cases"] == []
    finally:
        client.delete(f"/programs/{mine}", headers=other_headers)


def test_cases_from_another_engagement_never_count(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    other = client.post("/programs", json={"name": "Second"}, headers=auth_headers).json()["id"]
    try:
        store(client, auth_headers, other, spec("orders", "GET", "/orders/42", [OWNER, PEER], EXPECT))
        data = coverage(client, auth_headers, program_id)
        assert operation(data, "GET", "/orders/{id}")["state"] == "untested"
        assert data["identities"] == []
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)


# --------------------------------------------------------------------------- #
# Drafting a case for an operation from the engagement's existing identities
# --------------------------------------------------------------------------- #

def preview(client, headers, pid, **body):
    return client.post(f"/engagements/{pid}/test-cases/preview", headers=headers, json=body)


def test_draft_reuses_engagement_identities_as_references_only(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, spec("orders", "GET", "/orders/42", [OWNER, PEER, TENANT_B, ANONYMOUS], EXPECT))
    endpoint = coverage(client, auth_headers, program_id)["operations"][0]["endpoint_id"]

    res = preview(client, auth_headers, program_id, endpoint_ids=[endpoint], identity_ids=["tenant-b", "owner", "anonymous"])
    assert res.status_code == 200, res.text
    draft = res.json()["drafts"][0]["spec"]
    assert [i["id"] for i in draft["identities"]] == ["tenant-b", "owner", "anonymous"]
    assert draft["identities"][0]["credential"] == {"type": "bearer", "value_env": "TENANT_B_TOKEN"}
    assert draft["identities"][2]["credential"] == {"type": "static_header"}
    # Access policy is never inferred: every decision stays at skip until a human sets it.
    assert {e["decision"] for e in draft["expected_access"]} == {"skip"}
    assert not any("preflight" in i or "value" in i["credential"] for i in draft["identities"])


def test_drafts_without_identity_ids_are_unchanged(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    endpoint = coverage(client, auth_headers, program_id)["operations"][0]["endpoint_id"]
    draft = preview(client, auth_headers, program_id, endpoint_ids=[endpoint]).json()["drafts"][0]["spec"]
    assert [i["id"] for i in draft["identities"]] == ["anonymous", "member"]


def test_unknown_identities_are_refused_and_other_engagements_never_leak(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    endpoint = coverage(client, auth_headers, program_id)["operations"][0]["endpoint_id"]
    other = client.post("/programs", json={"name": "Elsewhere"}, headers=auth_headers).json()["id"]
    try:
        store(client, auth_headers, other, spec("secret-case", "GET", "/x/1", [identity("elsewhere-only")], {"elsewhere-only": "allow"}))
        res = preview(client, auth_headers, program_id, endpoint_ids=[endpoint], identity_ids=["elsewhere-only"])
        assert res.status_code == 400 and "elsewhere-only" in res.text
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)


def test_drafting_stores_nothing_and_respects_engagement_access(client, auth_headers, other_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, spec("orders", "GET", "/orders/42", [OWNER, PEER], EXPECT))
    endpoint = coverage(client, auth_headers, program_id)["operations"][0]["endpoint_id"]
    db = SessionLocal()
    try:
        before = db.query(AuthorizationTestCase).count()
    finally:
        db.close()
    assert preview(client, auth_headers, program_id, endpoint_ids=[endpoint], identity_ids=["owner"]).status_code == 200
    assert preview(client, other_headers, program_id, endpoint_ids=[endpoint], identity_ids=["owner"]).status_code == 404
    db = SessionLocal()
    try:
        assert db.query(AuthorizationTestCase).count() == before
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Why a boundary may matter, and the order to look in
# --------------------------------------------------------------------------- #

def reasons(op):
    return {r["code"] for r in op["priority_reasons"]}


def test_priority_reasons_come_only_from_captured_facts(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7", label="owner")
    capture(client, auth_headers, program_id, "GET", "/orders/8", label="peer")
    capture(client, auth_headers, program_id, "POST", "/orders/7/refund", body='{"amount": 5, "role": "admin"}')
    capture(client, auth_headers, program_id, "GET", "/health", label="anonymous")
    capture(client, auth_headers, program_id, "GET", "/denied/1", label="peer", status=403)
    data = coverage(client, auth_headers, program_id)

    orders = operation(data, "GET", "/orders/{id}")
    assert reasons(orders) == {"object_identifier_in_path", "success_for_multiple_identities"}
    refund = operation(data, "POST", "/orders/{id}/refund")
    assert reasons(refund) == {"object_identifier_in_path", "state_changing_method", "boundary_fields_in_requests"}
    assert "role" in next(r for r in refund["priority_reasons"] if r["code"] == "boundary_fields_in_requests")["detail"]
    assert reasons(operation(data, "GET", "/health")) == {"anonymous_success_observed"}
    # A refused request is not evidence of access, and a plain static route has no reason to flag.
    assert reasons(operation(data, "GET", "/denied/{id}")) == {"object_identifier_in_path"}


def test_priority_sort_is_deterministic_and_never_hides_operations(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    capture(client, auth_headers, program_id, "GET", "/orders/8", label="peer")
    default = coverage(client, auth_headers, program_id)
    ranked = coverage(client, auth_headers, program_id, sort="priority")
    assert ranked["filtered_total"] == default["filtered_total"] == 6
    assert {o["endpoint_id"] for o in ranked["operations"]} == {o["endpoint_id"] for o in default["operations"]}
    order = [o["state"] for o in ranked["operations"]]
    assert order[0] == "violation_candidate"
    assert order.index("untested") < order.index("reviewed_not_executed") < order.index("inconclusive")
    assert order.index("inconclusive") < order.index("partial") < order.index("conclusive")
    assert [o["endpoint_id"] for o in ranked["operations"]] == [
        o["endpoint_id"] for o in coverage(client, auth_headers, program_id, sort="priority")["operations"]
    ]
    assert client.get(f"/engagements/{program_id}/api/coverage", headers=auth_headers, params={"sort": "random"}).status_code == 422


def test_more_captured_reasons_rank_first_within_a_state(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/plain")
    capture(client, auth_headers, program_id, "DELETE", "/orders/7")
    ranked = coverage(client, auth_headers, program_id, sort="priority")["operations"]
    assert [o["path_template"] for o in ranked] == ["/orders/{id}", "/plain"]


def test_candidate_evidence_points_at_the_retained_redacted_record(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["candidates"]["backing_evidence"] == len(op["candidate_evidence"]) == 1
    ref = op["candidate_evidence"][0]
    assert (ref["identity_id"], ref["expected"], ref["observed"]) == ("peer", "deny", "allow")
    # The reference resolves through the ordinary evidence endpoint, redacted and hash-checked.
    rows = client.get(
        f"/engagements/{program_id}/evidence",
        headers=auth_headers,
        params={"job_id": ref["job_id"], "case_id": ref["case_id"], "identity_id": ref["identity_id"]},
    ).json()["evidence"]
    assert [r["id"] for r in rows] == [ref["evidence_id"]]
    assert rows[0]["content_hash"] == ref["content_hash"] and rows[0]["redacted"] is True


def test_operations_without_a_candidate_carry_no_evidence_references(client, auth_headers, program_id):
    build_engagement(client, auth_headers, program_id)
    data = coverage(client, auth_headers, program_id)
    assert operation(data, "GET", "/reports/{id}")["candidate_evidence"] == []
    assert operation(data, "GET", "/profile")["candidate_evidence"] == []


# --------------------------------------------------------------------------- #
# Integrity: a changed case must not inherit the coverage of what it never ran
# --------------------------------------------------------------------------- #

def edit_case(client, headers, pid, case_id, new_spec):
    res = client.patch(f"/engagements/{pid}/test-cases/{case_id}", headers=headers, json={"spec": new_spec})
    assert res.status_code == 200, res.text


def prepared(client, headers, pid, paths=("/orders/7", "/invoices/9", "/profile")):
    for path in paths:
        capture(client, headers, pid, "GET", path)
    original = spec("orders", "GET", "/orders/42", [OWNER, PEER], EXPECT)
    case_id = store(client, headers, pid, original, "orders")
    return original, case_id


def clean_pair():
    return [run("allow", 200, "owner"), run("deny", 403, "peer")]


def test_a_baseline_run_of_an_unchanged_case_is_current_coverage(client, auth_headers, program_id):
    original, case_id = prepared(client, auth_headers, program_id)
    execute(client, auth_headers, program_id, case_id, original, clean_pair())
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["state"] == "conclusive" and op["historical_assessments"] == []


def test_repointing_a_case_does_not_credit_the_new_operation(client, auth_headers, program_id):
    original, case_id = prepared(client, auth_headers, program_id)
    execute(client, auth_headers, program_id, case_id, original, clean_pair())
    moved = spec("orders", "GET", "/invoices/55", [OWNER, PEER], EXPECT)
    edit_case(client, auth_headers, program_id, case_id, moved)
    data = coverage(client, auth_headers, program_id)
    invoices = operation(data, "GET", "/invoices/{id}")
    assert invoices["state"] == "stale"  # reviewed, but the current definition was never run
    assert invoices["cases"][0]["executed"] is False
    assert all(
        row["state"] == "reviewed_not_run"
        for row in invoices["identity_coverage"]
        if row["identity_id"] in {"owner", "peer"}
    )
    # What did run is still attributed to the operation it actually exercised.
    orders = operation(data, "GET", "/orders/{id}")
    assert orders["state"] == "untested"
    assert [h["reason"] for h in orders["historical_assessments"]] == ["case_modified"]
    assert orders["historical_assessments"][0]["assessment_status"] == "conclusive"


def test_changing_the_method_identities_or_expectations_makes_a_run_stale(client, auth_headers, program_id):
    changes = {
        "method": lambda s: {**s, "request": {**s["request"], "method": "HEAD"}},
        "identity added": lambda s: {
            **s,
            "identities": s["identities"] + [ADMIN],
            "expected_access": s["expected_access"] + [{"identity_id": "admin", "decision": "allow"}],
        },
        "identity removed": lambda s: {
            **s,
            "identities": s["identities"][:1],
            "expected_access": s["expected_access"][:1],
        },
        "decision changed": lambda s: {
            **s,
            "expected_access": [
                {"identity_id": "owner", "decision": "allow"},
                {"identity_id": "peer", "decision": "allow"},
            ],
        },
        "context added": lambda s: {**s, "resource": {"owner_identity": "owner", "type": "order", "object_id": "42"}},
    }
    for label, change in changes.items():
        original, case_id = prepared(client, auth_headers, program_id)
        execute(client, auth_headers, program_id, case_id, original, clean_pair())
        edit_case(client, auth_headers, program_id, case_id, change(original))
        data = coverage(client, auth_headers, program_id)
        assert all(o["state"] != "conclusive" for o in data["operations"]), label
        orders = operation(data, "GET", "/orders/{id}")
        if label == "method":
            # HEAD /orders/{id} was never observed: the edited case now covers nothing.
            assert [c["reason"] for c in data["unmatched_cases"]] == ["no_observed_operation"]
            assert orders["state"] == "untested"
            assert [h["reason"] for h in orders["historical_assessments"]] == ["case_modified"]
        else:
            assert orders["state"] == "stale", f"{label}: the edited case inherited the old run"
            assert orders["cases"][0]["executed"] is False and orders["cases"][0]["stale_runs"] == 1
        client.delete(f"/engagements/{program_id}/test-cases/{case_id}", headers=auth_headers)


def test_renaming_a_case_does_not_invalidate_its_run(client, auth_headers, program_id):
    original, case_id = prepared(client, auth_headers, program_id)
    execute(client, auth_headers, program_id, case_id, original, clean_pair())
    res = client.patch(
        f"/engagements/{program_id}/test-cases/{case_id}",
        headers=auth_headers,
        json={"name": "renamed", "description": "notes"},
    )
    assert res.status_code == 200
    assert operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")["state"] == "conclusive"


def test_a_recorded_candidate_stays_attached_to_the_operation_it_was_found_on(client, auth_headers, program_id):
    original, case_id = prepared(client, auth_headers, program_id)
    finding = {"category": "potential_bola", "severity": "high", "message": "peer read the order"}
    execute(client, auth_headers, program_id, case_id, original,
            [run("allow", 200, "owner"), run("allow", 200, "peer")], [finding])
    edit_case(client, auth_headers, program_id, case_id, spec("orders", "GET", "/invoices/55", [OWNER, PEER], EXPECT))
    data = coverage(client, auth_headers, program_id)
    orders = operation(data, "GET", "/orders/{id}")
    assert orders["state"] == "violation_candidate" and orders["candidates"]["open"] == 1
    assert len(orders["candidate_evidence"]) == 1
    invoices = operation(data, "GET", "/invoices/{id}")
    assert invoices["candidates"]["open"] == 0 and invoices["state"] == "stale"


def test_a_deleted_case_leaves_its_history_and_findings_visible(client, auth_headers, program_id):
    original, case_id = prepared(client, auth_headers, program_id)
    execute(client, auth_headers, program_id, case_id, original, clean_pair())
    finding = {"category": "potential_bola", "severity": "high", "message": "x"}
    second = spec("orders-2", "GET", "/orders/43", [OWNER, PEER], EXPECT)
    second_id = store(client, auth_headers, program_id, second, "orders two")
    execute(client, auth_headers, program_id, second_id, second,
            [run("allow", 200, "owner"), run("allow", 200, "peer")], [finding])
    for doomed in (case_id, second_id):
        assert client.delete(f"/engagements/{program_id}/test-cases/{doomed}", headers=auth_headers).status_code in {200, 204}
    orders = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert orders["state"] == "violation_candidate"  # an unresolved finding outlives its case
    assert {h["reason"] for h in orders["historical_assessments"]} == {"case_deleted"}
    assert len(orders["historical_assessments"]) == 2


def test_a_run_whose_case_snapshot_was_not_verified_never_counts_as_current(client, auth_headers, program_id):
    original, case_id = prepared(client, auth_headers, program_id)
    job = queue(client, auth_headers, program_id, case_id)
    assert client.post(f"/jobs/{job}/claim", headers=auth_headers).status_code == 200
    legacy = {"test_case_id": original["id"], "executions": clean_pair(), "findings": []}  # no case_hash
    assert client.post(f"/jobs/{job}/upload", headers=auth_headers, json=legacy).status_code == 200
    client.patch(f"/jobs/{job}", headers=auth_headers, json={"status": "done"})
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["state"] == "stale"
    assert [h["reason"] for h in op["historical_assessments"]] == ["snapshot_unverified"]


# --------------------------------------------------------------------------- #
# Integrity: combining several cases must not manufacture certainty
# --------------------------------------------------------------------------- #

def two_cases(client, headers, pid):
    capture(client, headers, pid, "GET", "/orders/7")
    first = spec("orders-a", "GET", "/orders/42", [OWNER, PEER], EXPECT)
    second = spec("orders-b", "GET", "/orders/43", [OWNER, PEER], EXPECT)
    return first, store(client, headers, pid, first, "a"), second, store(client, headers, pid, second, "b")


def test_one_inconclusive_case_prevents_a_conclusive_operation(client, auth_headers, program_id):
    first, first_id, second, second_id = two_cases(client, auth_headers, program_id)
    execute(client, auth_headers, program_id, first_id, first, clean_pair())
    execute(client, auth_headers, program_id, second_id, second,
            [run("allow", 200, "owner"), run("server_error", 503, "peer")])
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["state"] == "partial"
    peer = identity_states(op)["peer"]
    assert peer["state"] == "mixed" and peer["reason"] == "evaluated_in_some_cases_only"
    assert identity_states(op)["owner"]["state"] == "evaluated"


def test_an_unrun_second_case_keeps_the_operation_from_being_conclusive(client, auth_headers, program_id):
    first, first_id, second, second_id = two_cases(client, auth_headers, program_id)
    execute(client, auth_headers, program_id, first_id, first, clean_pair())
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["state"] == "partial"
    assert identity_states(op)["peer"]["state"] == "mixed"


def test_every_case_conclusive_and_current_is_conclusive(client, auth_headers, program_id):
    first, first_id, second, second_id = two_cases(client, auth_headers, program_id)
    execute(client, auth_headers, program_id, first_id, first, clean_pair())
    execute(client, auth_headers, program_id, second_id, second, clean_pair())
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["state"] == "conclusive"
    assert identity_states(op)["peer"]["state"] == "evaluated"


def test_a_candidate_from_one_case_outweighs_a_conclusive_other(client, auth_headers, program_id):
    first, first_id, second, second_id = two_cases(client, auth_headers, program_id)
    execute(client, auth_headers, program_id, first_id, first, clean_pair())
    finding = {"category": "potential_bola", "severity": "high", "message": "peer"}
    execute(client, auth_headers, program_id, second_id, second,
            [run("allow", 200, "owner"), run("allow", 200, "peer")], [finding])
    op = operation(coverage(client, auth_headers, program_id), "GET", "/orders/{id}")
    assert op["state"] == "violation_candidate" and op["candidates"]["open"] == 1
