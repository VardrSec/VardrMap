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


def capture(client, headers, pid, method, path, label="owner"):
    res = client.post(
        f"/engagements/{pid}/api/exchanges",
        headers=headers,
        json={"method": method, "url": f"{HOST}{path}", "identity_label": label, "response_status": 200},
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
