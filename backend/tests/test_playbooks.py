import pytest
from playbooks import CATALOG, ApiPlaybook
from pydantic import ValidationError


def test_original_catalog_is_versioned_and_cannot_record_coverage():
    assert set(CATALOG) == {"API-01", "API-02", "API-03"}
    for book in CATALOG.values():
        assert (
            book.version == "1.0"
            and book.prerequisites
            and book.steps
            and book.manual_remainder
        )
        with pytest.raises(ValidationError):
            ApiPlaybook.model_validate({**book.model_dump(), "covered": True})


def test_playbook_reads_require_owned_engagement_and_auth(
    client, auth_headers, other_headers, program_id
):
    base = f"/engagements/{program_id}/playbooks"
    for path in (base, base + "/API-01"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=other_headers).status_code == 404
        assert (
            client.get(path, headers={"Authorization": "Bearer invalid"}).status_code
            == 401
        )
        assert client.get(path, headers=auth_headers).status_code == 200
    assert client.get(base + "/API-99", headers=auth_headers).status_code == 404
    catalog = client.get(base, headers=auth_headers).json()
    assert catalog["total"] == 3
    assert "steps" not in catalog["playbooks"][0]
    assert (
        client.get(base + "/API-01", headers=auth_headers).json()
        == CATALOG["API-01"].model_dump()
    )


def test_viewer_reads_guidance_until_membership_is_revoked(
    client, auth_headers, other_headers, program_id
):
    res = client.post(
        f"/engagements/{program_id}/members",
        headers=auth_headers,
        json={"github_id": "gh_user2", "role": "viewer"},
    )
    assert res.status_code == 201, res.text
    base = f"/engagements/{program_id}/playbooks"
    assert client.get(base, headers=other_headers).status_code == 200
    assert client.get(base + "/API-03", headers=other_headers).status_code == 200
    assert (
        client.delete(
            f"/engagements/{program_id}/members/gh_user2", headers=auth_headers
        ).status_code
        == 200
    )
    assert client.get(base, headers=other_headers).status_code == 404


@pytest.mark.parametrize("scope,status", [("full", 200), ("runner", 403)])
def test_playbook_key_scope_and_revocation(
    client, auth_headers, program_id, scope, status
):
    key = client.post(
        "/auth/apikeys",
        headers=auth_headers,
        json={"label": "Playbook fixture", "scope": scope},
    ).json()
    headers = {"Authorization": "Bearer " + key["token"]}
    path = f"/engagements/{program_id}/playbooks/API-02"
    try:
        assert client.get(path, headers=headers).status_code == status
    finally:
        client.delete(f"/auth/apikeys/{key['id']}", headers=auth_headers)
    assert client.get(path, headers=headers).status_code == 401
