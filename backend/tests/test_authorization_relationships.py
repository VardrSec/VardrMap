"""Boundary hypotheses from reviewed identity, tenant, role and resource context.

Synthetic data only. Tenants and roles exist solely where a case declared them:
the module must not guess either.
"""
from tests.test_authorization_coverage import (
    ADMIN,
    ANONYMOUS,
    EXPECT,
    capture,
    clean_run,
    execute,
    run,
    spec,
    store,
)

OWNER_A = {"id": "owner", "role": "user", "tenant_id": "tenant-a", "credential": {"type": "bearer", "value_env": "OWNER_TOKEN"}}
PEER_A = {"id": "peer", "role": "user", "tenant_id": "tenant-a", "credential": {"type": "bearer", "value_env": "PEER_TOKEN"}}
OTHER_B = {"id": "tenant-b", "role": "user", "tenant_id": "tenant-b", "credential": {"type": "bearer", "value_env": "TENANT_B_TOKEN"}}
ADMIN_A = {**ADMIN, "role": "admin", "tenant_id": "tenant-a"}
CAST = [OWNER_A, PEER_A, OTHER_B, ADMIN_A, ANONYMOUS]


def case(case_id, path, people=CAST, resource=True, hierarchy=True, expect=EXPECT):
    value = spec(case_id, "GET", path, people, expect)
    if resource:
        value["resource"] = {"owner_identity": "owner", "type": "order", "object_id": "42"}
    if hierarchy:
        value["role_hierarchy"] = ["user", "admin"]
    return value


def relationships(client, headers, pid):
    res = client.get(f"/engagements/{pid}/api/relationships", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def hypotheses(data, operation=None):
    return {
        (h["operation"], h["boundary"]): h
        for h in data["hypotheses"]
        if operation is None or h["operation"] == operation
    }


def results_for(people):
    rows = []
    for person in people:
        who = person["id"]
        rows.append(run("allow", 200, who) if EXPECT[who] == "allow" else run("deny", 403, who))
    return rows


def test_identities_tenants_and_askable_boundaries_come_from_declared_attributes(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, case("orders", "/orders/42"))
    data = relationships(client, auth_headers, program_id)
    assert data["tenants"] == ["tenant-a", "tenant-b"]
    table = {i["identity_id"]: i for i in data["identities"]}
    assert table["tenant-b"]["tenant_id"] == "tenant-b" and table["admin"]["role"] == "admin"
    assert table["anonymous"]["anonymous"] is True
    assert data["askable_boundaries"] == {
        "cross_tenant": True, "same_tenant_peer": True, "higher_privilege": True, "anonymous": True,
    }


def test_an_untested_operation_gets_a_question_for_each_askable_boundary(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, case("elsewhere", "/never/1"))  # supplies identities only
    found = hypotheses(relationships(client, auth_headers, program_id), "GET /orders/{id}")
    assert {b for _, b in found} == {"cross_tenant", "same_tenant_peer", "higher_privilege", "anonymous"}
    assert all(h["status"] == "untested" for h in found.values())
    cross = found[("GET /orders/{id}", "cross_tenant")]
    assert "tenant-a" in cross["basis"][0] and "tenant-b" in cross["basis"][0]
    assert "different tenant" in cross["question"]


def test_an_evaluated_result_for_a_boundary_removes_its_question(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    tested = case("orders", "/orders/42")
    case_id = store(client, auth_headers, program_id, tested)
    execute(client, auth_headers, program_id, case_id, tested, results_for(CAST))
    found = hypotheses(relationships(client, auth_headers, program_id), "GET /orders/{id}")
    assert found == {}  # every askable boundary has a current evaluated result


def test_a_boundary_only_partly_evidenced_still_has_a_question(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    tested = case("orders", "/orders/42")
    case_id = store(client, auth_headers, program_id, tested)
    rows = results_for(CAST)
    rows[2] = run("server_error", 503, "tenant-b")  # the cross-tenant caller got no definite answer
    execute(client, auth_headers, program_id, case_id, tested, rows)
    found = hypotheses(relationships(client, auth_headers, program_id), "GET /orders/{id}")
    assert set(found) == {("GET /orders/{id}", "cross_tenant")}
    assert found[("GET /orders/{id}", "cross_tenant")]["status"] == "inconclusive"


def test_a_reviewed_but_unrun_case_is_reported_as_not_run(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, case("orders", "/orders/42"))
    found = hypotheses(relationships(client, auth_headers, program_id), "GET /orders/{id}")
    assert {h["status"] for h in found.values()} == {"reviewed_not_run"}


def test_cases_without_a_resource_owner_cannot_tell_boundaries_apart(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    bare = case("orders", "/orders/42", resource=False)
    case_id = store(client, auth_headers, program_id, bare)
    execute(client, auth_headers, program_id, case_id, bare, results_for(CAST))
    found = hypotheses(relationships(client, auth_headers, program_id), "GET /orders/{id}")
    assert found[("GET /orders/{id}", "cross_tenant")]["status"] == "owner_context_missing"
    assert "no resource owner" in found[("GET /orders/{id}", "cross_tenant")]["basis"][-1]
    assert ("GET /orders/{id}", "anonymous") not in found  # needs no owner and was evaluated


def test_boundaries_are_not_invented_when_attributes_were_never_declared(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    plain = [{"id": "alice", "credential": {"type": "bearer", "value_env": "A"}}, {"id": "bob", "credential": {"type": "bearer", "value_env": "B"}}]
    store(client, auth_headers, program_id, spec("c", "GET", "/orders/42", plain, {"alice": "allow", "bob": "deny"}))
    data = relationships(client, auth_headers, program_id)
    assert data["tenants"] == [] and set(data["askable_boundaries"].values()) == {False}
    assert data["hypotheses"] == []


def test_identities_missing_a_tenant_are_listed_when_others_declare_one(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    drifter = {"id": "contractor", "credential": {"type": "bearer", "value_env": "C"}}
    store(client, auth_headers, program_id, case("orders", "/orders/42", [OWNER_A, OTHER_B, drifter], expect={**EXPECT, "contractor": "deny"}))
    assert relationships(client, auth_headers, program_id)["identities_without_tenant"] == ["contractor"]


def test_a_changed_case_no_longer_counts_as_evaluated_evidence(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    tested = case("orders", "/orders/42")
    case_id = store(client, auth_headers, program_id, tested)
    execute(client, auth_headers, program_id, case_id, tested, results_for(CAST))
    assert hypotheses(relationships(client, auth_headers, program_id)) == {}
    edited = {**tested, "resource": {**tested["resource"], "tenant_id": "tenant-b"}}
    res = client.patch(f"/engagements/{program_id}/test-cases/{case_id}", headers=auth_headers, json={"spec": edited})
    assert res.status_code == 200
    # The earlier run belonged to the old definition, so the boundaries are questions again.
    assert hypotheses(relationships(client, auth_headers, program_id))


def test_relationships_are_read_only_isolated_and_authenticated(client, auth_headers, other_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, case("orders", "/orders/42"))
    assert client.get(f"/engagements/{program_id}/api/relationships").status_code == 401
    assert client.get(f"/engagements/{program_id}/api/relationships", headers=other_headers).status_code == 404
    mine = client.post("/programs", json={"name": "Other"}, headers=other_headers).json()["id"]
    try:
        theirs = relationships(client, other_headers, mine)
        assert theirs["identities"] == [] and theirs["hypotheses"] == []
    finally:
        client.delete(f"/programs/{mine}", headers=other_headers)
