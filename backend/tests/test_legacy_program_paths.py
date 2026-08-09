"""The retired /programs/* paths must keep working.

VardrRunner deploys from its own repository and personal API keys are used from
Burp and ad-hoc scripts, so the rename cannot break the old paths the moment
this backend ships. These tests pin that guarantee — the rest of the suite
exercises it incidentally, this file states it on purpose.
"""


def test_legacy_list_path_still_works(client, auth_headers):
    assert client.get("/programs", headers=auth_headers).status_code == 200


def test_legacy_and_new_paths_return_the_same_engagement(client, auth_headers, program_id):
    legacy = client.get(f"/programs/{program_id}", headers=auth_headers)
    modern = client.get(f"/engagements/{program_id}", headers=auth_headers)
    assert legacy.status_code == 200
    assert modern.status_code == 200
    assert legacy.json()["id"] == modern.json()["id"] == program_id


def test_legacy_nested_paths_work(client, auth_headers, program_id):
    """The runner reads scope, recon, services and imports through these."""
    for suffix in ("scope", "recon", "services", "findings"):
        res = client.get(f"/programs/{program_id}/{suffix}", headers=auth_headers)
        assert res.status_code == 200, f"/programs/{{id}}/{suffix} -> {res.status_code}"


def test_legacy_write_path_works(client, auth_headers, program_id):
    res = client.post(
        f"/programs/{program_id}/scope/in",
        json={"value": "legacy.example.com", "kind": "domain"},
        headers=auth_headers,
    )
    assert res.status_code == 200


def test_rewrite_does_not_catch_a_prefix_match(client, auth_headers):
    """/programsomething must not be rewritten into /engagementsomething."""
    res = client.get("/programsomething", headers=auth_headers)
    assert res.status_code == 404


def test_unrelated_paths_are_untouched(client, auth_headers):
    assert client.get("/health").status_code == 200
    assert client.get("/me", headers=auth_headers).status_code == 200
    assert client.get("/clients", headers=auth_headers).status_code == 200


def test_legacy_path_still_enforces_auth(client, program_id):
    """The alias must not become a way around authentication."""
    assert client.get(f"/programs/{program_id}").status_code == 401


def test_legacy_path_still_enforces_ownership(client, other_headers, program_id):
    assert client.get(f"/programs/{program_id}", headers=other_headers).status_code == 404
