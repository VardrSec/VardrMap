"""Finding CRUD and BOLA/IDOR ownership checks."""

_FINDING = {"title": "XSS in search", "severity": "high", "asset": "example.com", "status": "new"}


def test_add_finding_to_own_program(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/findings", json=_FINDING, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "XSS in search"
    assert data["severity"] == "high"
    assert "id" in data


def test_add_finding_to_other_users_program_returns_404(client, other_headers, program_id):
    res = client.post(f"/programs/{program_id}/findings", json=_FINDING, headers=other_headers)
    assert res.status_code == 404


def test_update_finding_in_own_program(client, auth_headers, program_id):
    fid = client.post(f"/programs/{program_id}/findings", json=_FINDING, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/findings/{fid}", json={"status": "triaged"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "triaged"


def test_update_finding_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    fid = client.post(f"/programs/{program_id}/findings", json=_FINDING, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/findings/{fid}", json={"status": "closed"}, headers=other_headers)
    assert res.status_code == 404


def test_delete_finding_from_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    fid = client.post(f"/programs/{program_id}/findings", json=_FINDING, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/findings/{fid}", headers=other_headers)
    assert res.status_code == 404


def test_list_findings_for_other_users_program_returns_404(client, other_headers, program_id):
    res = client.get(f"/programs/{program_id}/findings", headers=other_headers)
    assert res.status_code == 404
