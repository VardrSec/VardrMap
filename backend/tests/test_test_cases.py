"""Stored VardrGate authorization test cases.

The load-bearing test here is that a literal credential cannot be stored. Every
other check mirrors VardrGate's own `validate()` so a case that would fail at run
time on the operator's machine is refused at write time instead.
"""
import copy


def _spec(**overrides) -> dict:
    """A minimal valid BOLA case, using secret references rather than literals."""
    spec = {
        "id": "bola-resource-ownership-check",
        "description": "A regular user must not read another user's resource.",
        "identities": [
            {
                "id": "admin",
                "credential": {"type": "bearer", "value_env": "ADMIN_TOKEN"},
            },
            {
                "id": "attacker",
                "credential": {"type": "bearer", "value_keychain": "attacker-token"},
            },
            {
                "id": "anonymous",
                "credential": {"type": "static_header", "header": "", "value": ""},
            },
        ],
        "request": {
            "method": "GET",
            "url": "https://api.example.com/users/42/profile",
        },
        "expected_access": [
            {"identity_id": "admin", "decision": "allow"},
            {"identity_id": "attacker", "decision": "deny"},
            {"identity_id": "anonymous", "decision": "deny"},
        ],
    }
    spec.update(overrides)
    return spec


def _create(client, headers, pid, **body):
    payload = {"name": "BOLA — user profile", "spec": _spec()}
    payload.update(body)
    return client.post(f"/programs/{pid}/test-cases", json=payload, headers=headers)


# --------------------------------------------------------------------------- #
# The rule that matters: no live secrets in the database
# --------------------------------------------------------------------------- #

def test_a_literal_credential_value_is_rejected(client, auth_headers, program_id):
    """VardrGate's own examples ship literal tokens. Storing one would put a live
    secret in the database and in every API response for the case.

    The fixture is deliberately not secret-shaped: what is under test is that a
    non-empty `value` is refused at all, not the shape of the string. Using a
    realistic token here would trip the secret scanner for no added coverage.
    """
    spec = _spec()
    spec["identities"][0]["credential"] = {"type": "bearer", "value": "a-literal-token"}
    res = _create(client, auth_headers, program_id, spec=spec)
    assert res.status_code == 400
    assert "value_env" in res.text


def test_an_empty_value_is_allowed_for_the_anonymous_identity(client, auth_headers, program_id):
    """`{"type": "static_header", "header": "", "value": ""}` is the legitimate
    anonymous caller in a BOLA case, not a leaked secret."""
    res = _create(client, auth_headers, program_id)
    assert res.status_code == 201, res.text


def test_a_bearer_identity_needs_a_secret_reference(client, auth_headers, program_id):
    spec = _spec()
    spec["identities"][0]["credential"] = {"type": "bearer"}
    res = _create(client, auth_headers, program_id, spec=spec)
    assert res.status_code == 400
    assert "value_env" in res.text


def test_two_secret_references_are_rejected(client, auth_headers, program_id):
    spec = _spec()
    spec["identities"][0]["credential"] = {
        "type": "bearer",
        "value_env": "ADMIN_TOKEN",
        "value_keychain": "admin-token",
    }
    res = _create(client, auth_headers, program_id, spec=spec)
    assert res.status_code == 400


def test_a_stored_case_round_trips_references_and_no_populated_value(
    client, auth_headers, program_id
):
    """What comes back must carry the reference, never a populated secret."""
    created = _create(client, auth_headers, program_id).json()
    fetched = client.get(
        f"/programs/{program_id}/test-cases/{created['id']}", headers=auth_headers
    ).json()

    creds = [i["credential"] for i in fetched["spec"]["identities"]]
    assert creds[0]["value_env"] == "ADMIN_TOKEN"
    assert creds[1]["value_keychain"] == "attacker-token"
    # No credential may come back with a non-empty value, on any identity.
    assert all(not str(c.get("value") or "").strip() for c in creds)


# --------------------------------------------------------------------------- #
# Shape checks mirroring VardrGate's validate()
# --------------------------------------------------------------------------- #

def test_create_returns_the_stored_case(client, auth_headers, program_id):
    res = _create(client, auth_headers, program_id)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["name"] == "BOLA — user profile"
    # The VardrGate id is surfaced so a result can be traced back without
    # opening the blob.
    assert data["test_case_id"] == "bola-resource-ownership-check"
    assert data["spec"]["request"]["method"] == "GET"


def test_spec_requires_an_id(client, auth_headers, program_id):
    spec = _spec()
    del spec["id"]
    assert _create(client, auth_headers, program_id, spec=spec).status_code == 400


def test_spec_requires_at_least_one_identity(client, auth_headers, program_id):
    assert _create(client, auth_headers, program_id, spec=_spec(identities=[])).status_code == 400


def test_duplicate_identity_ids_are_rejected(client, auth_headers, program_id):
    spec = _spec()
    spec["identities"][1]["id"] = "admin"
    assert _create(client, auth_headers, program_id, spec=spec).status_code == 400


def test_spec_requires_a_request_method_and_url(client, auth_headers, program_id):
    assert _create(
        client, auth_headers, program_id, spec=_spec(request={"url": "https://x.test"})
    ).status_code == 400
    assert _create(
        client, auth_headers, program_id, spec=_spec(request={"method": "GET"})
    ).status_code == 400


def test_expected_access_must_reference_a_declared_identity(client, auth_headers, program_id):
    spec = _spec()
    spec["expected_access"].append({"identity_id": "ghost", "decision": "deny"})
    res = _create(client, auth_headers, program_id, spec=spec)
    assert res.status_code == 400
    assert "does not match any identity" in res.text


def test_unknown_credential_type_is_rejected(client, auth_headers, program_id):
    spec = _spec()
    spec["identities"][0]["credential"] = {"type": "mtls", "value_env": "X"}
    assert _create(client, auth_headers, program_id, spec=spec).status_code == 400


def test_an_empty_spec_is_rejected(client, auth_headers, program_id):
    assert _create(client, auth_headers, program_id, spec={}).status_code == 400


# --------------------------------------------------------------------------- #
# CRUD and scoping
# --------------------------------------------------------------------------- #

def test_list_returns_the_engagements_cases(client, auth_headers, program_id):
    _create(client, auth_headers, program_id)
    res = client.get(f"/programs/{program_id}/test-cases", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()["test_cases"]) >= 1


def test_update_replaces_the_spec_and_refreshes_the_surfaced_id(
    client, auth_headers, program_id
):
    created = _create(client, auth_headers, program_id).json()
    revised = copy.deepcopy(created["spec"])
    revised["id"] = "bola-check-v2"

    res = client.patch(
        f"/programs/{program_id}/test-cases/{created['id']}",
        json={"spec": revised, "name": "BOLA v2"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["test_case_id"] == "bola-check-v2"
    assert res.json()["name"] == "BOLA v2"
    assert res.json()["updated_at"]


def test_update_rejects_a_spec_that_adds_a_literal_credential(
    client, auth_headers, program_id
):
    """The write-time rule has to hold on update too, not just create."""
    created = _create(client, auth_headers, program_id).json()
    revised = copy.deepcopy(created["spec"])
    revised["identities"][0]["credential"] = {"type": "bearer", "value": "leaked"}
    res = client.patch(
        f"/programs/{program_id}/test-cases/{created['id']}",
        json={"spec": revised},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_delete_removes_it(client, auth_headers, program_id):
    created = _create(client, auth_headers, program_id).json()
    assert client.delete(
        f"/programs/{program_id}/test-cases/{created['id']}", headers=auth_headers
    ).status_code == 200
    assert client.get(
        f"/programs/{program_id}/test-cases/{created['id']}", headers=auth_headers
    ).status_code == 404


def test_unauthenticated_is_rejected(client, program_id):
    assert client.get(f"/programs/{program_id}/test-cases").status_code == 401
    assert client.post(f"/programs/{program_id}/test-cases", json={}).status_code == 401


def test_another_user_gets_404(client, auth_headers, other_headers, program_id):
    created = _create(client, auth_headers, program_id).json()
    assert client.get(
        f"/programs/{program_id}/test-cases", headers=other_headers
    ).status_code == 404
    assert client.get(
        f"/programs/{program_id}/test-cases/{created['id']}", headers=other_headers
    ).status_code == 404
    assert client.delete(
        f"/programs/{program_id}/test-cases/{created['id']}", headers=other_headers
    ).status_code == 404


def test_a_case_from_another_engagement_is_not_reachable(client, auth_headers, program_id):
    """The id must be scoped to the engagement in the path, not looked up globally."""
    other = client.post("/programs", json={"name": "Other"}, headers=auth_headers).json()["id"]
    created = _create(client, auth_headers, other).json()
    try:
        assert client.get(
            f"/programs/{program_id}/test-cases/{created['id']}", headers=auth_headers
        ).status_code == 404
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)
