"""Boundary hypotheses from reviewed identity, tenant, role and resource context.

Synthetic data only. Tenants and roles exist solely where a case declared them:
the module must not guess either.
"""
import pytest

from db import SessionLocal
from models import AuthorizationTestCase
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


# --------------------------------------------------------------------------- #
# Relationship integrity: contradictions are reported, never silently resolved
# --------------------------------------------------------------------------- #

def person(name, tenant=None, role=None, env=None):
    value = {"id": name, "credential": {"type": "bearer", "value_env": env or f"{name.upper()}_TOKEN"}}
    if tenant:
        value["tenant_id"] = tenant
    if role:
        value["role"] = role
    return value


def owned_case(case_id, path, people, expect, tenant=None):
    value = spec(case_id, "GET", path, people, expect)
    value["resource"] = {"owner_identity": people[0]["id"], **({"tenant_id": tenant} if tenant else {})}
    return value


def test_conflicting_tenant_declarations_are_reported_not_resolved(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, owned_case("a", "/orders/42", [person("owner", "tenant-a"), person("peer", "tenant-a")], {"owner": "allow", "peer": "deny"}))
    store(client, auth_headers, program_id, owned_case("b", "/orders/43", [person("owner", "tenant-a"), person("peer", "tenant-b")], {"owner": "allow", "peer": "deny"}))
    data = relationships(client, auth_headers, program_id)
    conflict = next(c for c in data["identity_conflicts"] if c["identity_id"] == "peer" and c["attribute"] == "tenant_id")
    assert conflict["values"] == ["tenant-a", "tenant-b"]
    table = {i["identity_id"]: i for i in data["identities"]}
    assert table["peer"]["tenant_id"] is None and table["peer"]["conflicts"] == ["tenant_id"]
    assert table["owner"]["tenant_id"] == "tenant-a"  # consistent declarations stay established
    # With peer's tenant contradictory, only one tenant is established, so no cross-tenant question is manufactured.
    assert data["askable_boundaries"]["cross_tenant"] is False


def test_each_case_is_classified_by_its_own_declarations(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    first = owned_case("a", "/orders/42", [person("owner", "tenant-a"), person("peer", "tenant-a")], {"owner": "allow", "peer": "deny"})
    second = owned_case("b", "/orders/43", [person("owner", "tenant-b"), person("peer", "tenant-b")], {"owner": "allow", "peer": "deny"})
    store(client, auth_headers, program_id, first)
    second_id = store(client, auth_headers, program_id, second)
    execute(client, auth_headers, program_id, second_id, second, [run("allow", 200, "owner"), run("deny", 403, "peer")])
    found = hypotheses(relationships(client, auth_headers, program_id), "GET /orders/{id}")
    # In case b peer shares the owner's tenant; case a's tenant-a must not turn that into a cross-tenant result.
    assert ("GET /orders/{id}", "same_tenant_peer") not in found
    assert ("GET /orders/{id}", "cross_tenant") not in found or found[("GET /orders/{id}", "cross_tenant")]["status"] != "inconclusive"


def test_an_undeclared_attribute_is_not_borrowed_from_an_unrelated_case(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, owned_case("elsewhere", "/never/1", [person("owner", "tenant-a"), person("other", "tenant-b")], {"owner": "allow", "other": "deny"}))
    bare = owned_case("orders", "/orders/42", [person("owner"), person("other")], {"owner": "allow", "other": "deny"})
    case_id = store(client, auth_headers, program_id, bare)
    execute(client, auth_headers, program_id, case_id, bare, [run("allow", 200, "owner"), run("deny", 403, "other")])
    found = hypotheses(relationships(client, auth_headers, program_id), "GET /orders/{id}")
    # The evaluated case declares no tenants, so it establishes no cross-tenant relationship, however the ids match elsewhere.
    assert found[("GET /orders/{id}", "cross_tenant")]["status"] == "untested"


def test_a_credential_kind_conflict_prevents_an_anonymous_claim(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    as_anonymous = spec("a", "GET", "/orders/42", [person("owner", "tenant-a"), {"id": "guest", "credential": {"type": "static_header"}}], {"owner": "allow", "guest": "deny"})
    as_bearer = spec("b", "GET", "/orders/43", [person("owner", "tenant-a"), person("guest", "tenant-a")], {"owner": "allow", "guest": "deny"})
    store(client, auth_headers, program_id, as_anonymous)
    store(client, auth_headers, program_id, as_bearer)
    data = relationships(client, auth_headers, program_id)
    assert any(c["identity_id"] == "guest" and c["attribute"] == "credential" for c in data["identity_conflicts"])
    assert data["askable_boundaries"]["anonymous"] is False


def test_declarations_that_only_omit_an_attribute_do_not_conflict(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, owned_case("a", "/orders/42", [person("owner", "tenant-a"), person("peer", "tenant-a")], {"owner": "allow", "peer": "deny"}))
    store(client, auth_headers, program_id, owned_case("b", "/orders/43", [person("owner"), person("peer")], {"owner": "allow", "peer": "deny"}))
    data = relationships(client, auth_headers, program_id)
    assert data["identity_conflicts"] == []
    assert {i["identity_id"]: i["tenant_id"] for i in data["identities"]}["peer"] == "tenant-a"


def test_a_case_with_its_own_contradicting_tenants_is_classified_by_its_own_declarations(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, owned_case("a", "/orders/42", [person("owner", "tenant-a"), person("peer", "tenant-a")], {"owner": "allow", "peer": "deny"}))
    second = owned_case("b", "/orders/43", [person("owner", "tenant-a"), person("peer", "tenant-b")], {"owner": "allow", "peer": "deny"})
    second_id = store(client, auth_headers, program_id, second)
    execute(client, auth_headers, program_id, second_id, second, [run("allow", 200, "owner"), run("deny", 403, "peer")])
    data = relationships(client, auth_headers, program_id)
    evidence = next(e for e in data["boundary_evidence"] if e["operation"] == "GET /orders/{id}")
    # Case b itself declares peer in another tenant, so that run evaluated the cross-tenant boundary;
    # the first case's tenant-a for the same id must not relabel it as a same-tenant result.
    assert evidence["evaluated"] == {"cross_tenant": ["peer"]}


# --------------------------------------------------------------------------- #
# From a boundary question to a review-only draft
# --------------------------------------------------------------------------- #

def endpoint_id(client, headers, pid, path="/orders/{id}"):
    data = client.get(f"/engagements/{pid}/api/coverage", headers=headers).json()
    return next(o["endpoint_id"] for o in data["operations"] if o["path_template"] == path)


def boundary_draft(client, headers, pid, boundary, **extra):
    ep = endpoint_id(client, headers, pid)
    return client.post(
        f"/engagements/{pid}/test-cases/preview",
        headers=headers,
        json={"endpoint_ids": [ep], "boundary": boundary, **extra},
    )


def prepared_cast(client, headers, pid, owner_context=True):
    capture(client, headers, pid, "GET", "/orders/7")
    store(client, headers, pid, case("seed", "/orders/42", resource=owner_context))
    return client


def ids(draft):
    return [i["id"] for i in draft["spec"]["identities"]]


def test_cross_tenant_draft_uses_the_owner_and_other_tenant_identities_only(client, auth_headers, program_id):
    prepared_cast(client, auth_headers, program_id)
    res = boundary_draft(client, auth_headers, program_id, "cross_tenant")
    assert res.status_code == 200, res.text
    body = res.json()
    draft = body["drafts"][0]["spec"]
    assert ids(body["drafts"][0]) == ["owner", "tenant-b"]
    assert draft["resource"] == {"owner_identity": "owner", "tenant_id": "tenant-a"}
    assert {e["decision"] for e in draft["expected_access"]} == {"skip"}
    assert body["boundary_context"]["ready_to_run"] is False
    assert any("resource.type and resource.object_id" in line for line in body["boundary_context"]["missing_context"])


def test_same_tenant_peer_higher_privilege_and_anonymous_drafts(client, auth_headers, program_id):
    prepared_cast(client, auth_headers, program_id)
    peer = boundary_draft(client, auth_headers, program_id, "same_tenant_peer").json()
    assert ids(peer["drafts"][0])[0] == "owner" and set(ids(peer["drafts"][0])) == {"owner", "peer", "admin"}  # admin shares tenant-a with the owner
    higher = boundary_draft(client, auth_headers, program_id, "higher_privilege").json()
    assert ids(higher["drafts"][0]) == ["owner", "admin"]
    assert higher["drafts"][0]["spec"]["role_hierarchy"] == ["user", "admin"]
    anonymous = boundary_draft(client, auth_headers, program_id, "anonymous").json()
    assert ids(anonymous["drafts"][0]) == ["owner", "anonymous"]
    assert anonymous["drafts"][0]["spec"]["identities"][1]["credential"] == {"type": "static_header", "header": "", "value": ""}


def test_drafts_carry_credential_references_never_values(client, auth_headers, program_id):
    prepared_cast(client, auth_headers, program_id)
    body = boundary_draft(client, auth_headers, program_id, "cross_tenant").json()
    credentials = [i["credential"] for i in body["drafts"][0]["spec"]["identities"]]
    assert credentials == [
        {"type": "bearer", "value_env": "OWNER_TOKEN"},
        {"type": "bearer", "value_env": "TENANT_B_TOKEN"},
    ]
    assert all("value" not in credential for credential in credentials)  # references only


def test_missing_owner_context_is_reported_not_invented(client, auth_headers, program_id):
    prepared_cast(client, auth_headers, program_id, owner_context=False)
    body = boundary_draft(client, auth_headers, program_id, "cross_tenant").json()
    spec_value = body["drafts"][0]["spec"]
    assert "resource" not in spec_value
    assert any("resource.owner_identity" in line for line in body["boundary_context"]["missing_context"])
    assert body["boundary_context"]["ready_to_run"] is False
    assert {e["decision"] for e in spec_value["expected_access"]} == {"skip"}


def test_a_contradictory_identity_is_left_out_and_named(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, owned_case("a", "/orders/42", [person("owner", "tenant-a"), person("peer", "tenant-a"), person("visitor", "tenant-b")], {"owner": "allow", "peer": "deny", "visitor": "deny"}))
    store(client, auth_headers, program_id, owned_case("b", "/never/1", [person("owner", "tenant-a"), person("visitor", "tenant-c")], {"owner": "allow", "visitor": "deny"}))
    body = boundary_draft(client, auth_headers, program_id, "cross_tenant").json()
    assert "visitor" not in ids(body["drafts"][0])  # tenant-b vs tenant-c: not chosen arbitrarily
    assert {c["identity_id"] for c in body["boundary_context"]["conflicts"]} == {"visitor"}
    assert any("contradictory declarations" in line for line in body["boundary_context"]["missing_context"])


def test_the_identity_ids_draft_refuses_contradictory_identities(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    store(client, auth_headers, program_id, owned_case("a", "/orders/42", [person("owner", "tenant-a", env="OWNER_A")], {"owner": "allow"}))
    store(client, auth_headers, program_id, owned_case("b", "/never/1", [person("owner", "tenant-a", env="OWNER_B")], {"owner": "allow"}))
    res = client.post(
        f"/engagements/{program_id}/test-cases/preview",
        headers=auth_headers,
        json={"endpoint_ids": [endpoint_id(client, auth_headers, program_id)], "identity_ids": ["owner"]},
    )
    assert res.status_code == 400 and "Contradictory declarations for: owner" in res.text


def test_a_boundary_draft_needs_exactly_one_operation(client, auth_headers, program_id):
    prepared_cast(client, auth_headers, program_id)
    ep = endpoint_id(client, auth_headers, program_id)
    url = f"/engagements/{program_id}/test-cases/preview"
    assert client.post(url, headers=auth_headers, json={"endpoint_ids": [ep, ep], "boundary": "cross_tenant"}).status_code == 400
    assert client.post(url, headers=auth_headers, json={"openapi": {}, "boundary": "cross_tenant"}).status_code == 400
    assert client.post(url, headers=auth_headers, json={"endpoint_ids": [ep], "boundary": "cross_tenant", "identity_ids": ["owner"]}).status_code == 400
    assert client.post(url, headers=auth_headers, json={"endpoint_ids": [ep], "boundary": "bogus"}).status_code == 422


def test_mutating_operations_keep_their_explicit_safety_flag(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "PATCH", "/orders/7")
    patched = case("patch", "/orders/42")
    patched["request"]["method"] = "PATCH"
    patched["mutating"] = True
    store(client, auth_headers, program_id, patched)
    ep = endpoint_id(client, auth_headers, program_id)
    body = client.post(f"/engagements/{program_id}/test-cases/preview", headers=auth_headers, json={"endpoint_ids": [ep], "boundary": "cross_tenant"}).json()
    assert body["drafts"][0]["spec"]["mutating"] is True
    # Saving still demands the review confirmation and concrete decisions; nothing is stored by drafting.
    saved = client.post(f"/engagements/{program_id}/test-cases/reviewed", headers=auth_headers, json={"reviewed": True, "cases": [body["drafts"][0]]})
    assert saved.status_code == 400  # still skip decisions and an unresolved {id} in the URL


def test_drafting_never_reads_another_engagement_or_stores_anything(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")  # no cases here at all
    other = client.post("/programs", json={"name": "Elsewhere"}, headers=auth_headers).json()["id"]
    try:
        store(client, auth_headers, other, case("secret", "/x/1"))
        db = SessionLocal()
        try:
            before = db.query(AuthorizationTestCase).count()
        finally:
            db.close()
        body = boundary_draft(client, auth_headers, program_id, "cross_tenant").json()
        assert body["drafts"][0]["spec"]["identities"] == [
            {"id": "anonymous", "credential": {"type": "static_header", "header": "", "value": ""}},
            {"id": "member", "credential": {"type": "bearer", "value_env": "VARDRGATE_MEMBER_TOKEN"}},
        ] or body["drafts"][0]["spec"]["identities"] == []
        assert any("different tenant" in line or "owner" in line for line in body["boundary_context"]["missing_context"])
        db = SessionLocal()
        try:
            assert db.query(AuthorizationTestCase).count() == before
        finally:
            db.close()
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)


def test_boundary_drafts_respect_engagement_access(client, auth_headers, other_headers, program_id):
    prepared_cast(client, auth_headers, program_id)
    ep = endpoint_id(client, auth_headers, program_id)
    res = client.post(f"/engagements/{program_id}/test-cases/preview", headers=other_headers, json={"endpoint_ids": [ep], "boundary": "cross_tenant"})
    assert res.status_code == 404


def test_a_modified_case_with_history_still_drafts_from_its_current_declarations(client, auth_headers, program_id):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    tested = case("orders", "/orders/42")
    case_id = store(client, auth_headers, program_id, tested)
    execute(client, auth_headers, program_id, case_id, tested, results_for(CAST))
    edited = {**tested, "resource": {**tested["resource"], "tenant_id": "tenant-b"}}
    assert client.patch(f"/engagements/{program_id}/test-cases/{case_id}", headers=auth_headers, json={"spec": edited}).status_code == 200
    body = boundary_draft(client, auth_headers, program_id, "cross_tenant").json()
    assert body["drafts"][0]["spec"]["resource"]["tenant_id"] == "tenant-b"  # the current reviewed declaration
    data = relationships(client, auth_headers, program_id)
    assert hypotheses(data), "the earlier run must not hide the questions the edited case reopens"


@pytest.mark.parametrize("boundary, expected_ids", [
    ("cross_tenant", {"owner", "peer", "admin"}),
    ("same_tenant_peer", {"owner", "tenant-b"}),
])
def test_boundary_draft_uses_resource_tenant_instead_of_owner_tenant(client, auth_headers, program_id, boundary, expected_ids):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    reviewed = case("orders", "/orders/42")
    reviewed["resource"]["tenant_id"] = "tenant-b"
    store(client, auth_headers, program_id, reviewed)

    res = boundary_draft(client, auth_headers, program_id, boundary)
    assert res.status_code == 200, res.text
    body = res.json()
    draft = body["drafts"][0]
    assert set(ids(draft)) == expected_ids
    assert draft["spec"]["resource"] == {"owner_identity": "owner", "tenant_id": "tenant-b"}
    assert {e["decision"] for e in draft["spec"]["expected_access"]} == {"skip"}
    assert body["boundary_context"]["ready_to_run"] is False


@pytest.mark.parametrize("boundary", ["cross_tenant", "same_tenant_peer"])
@pytest.mark.parametrize("reverse", [False, True])
def test_boundary_draft_does_not_choose_between_conflicting_resource_tenants(client, auth_headers, program_id, boundary, reverse):
    capture(client, auth_headers, program_id, "GET", "/orders/7")
    declarations = [("a", "tenant-a"), ("b", "tenant-b")]
    for name, tenant in reversed(declarations) if reverse else declarations:
        reviewed = case(name, "/orders/42")
        reviewed["resource"]["tenant_id"] = tenant
        store(client, auth_headers, program_id, reviewed)

    res = boundary_draft(client, auth_headers, program_id, boundary)
    assert res.status_code == 200, res.text
    body = res.json()
    draft = body["drafts"][0]
    assert ids(draft) == ["owner"]
    assert draft["spec"]["resource"] == {"owner_identity": "owner"}
    assert any("resource.tenant_id" in gap and "different tenants" in gap for gap in body["boundary_context"]["missing_context"])
    assert {e["decision"] for e in draft["spec"]["expected_access"]} == {"skip"}
    assert body["boundary_context"]["ready_to_run"] is False
