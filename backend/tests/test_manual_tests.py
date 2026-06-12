"""Manual test CRUD and BOLA/IDOR ownership checks."""

_TEST = {"title": "Login bypass attempt", "hypothesis": "IDOR via user_id param", "payload": "user_id=2", "evidence": "Got 200", "status": "new"}


def test_list_manual_tests_empty(client, auth_headers, program_id):
    res = client.get(f"/programs/{program_id}/manual-tests", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["manual_tests"] == [] or isinstance(data["manual_tests"], list)
    assert "total" in data


def test_add_manual_test(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/manual-tests", json=_TEST, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == _TEST["title"]
    assert data["status"] == "new"
    assert "id" in data


def test_add_manual_test_minimal(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/manual-tests", json={"title": "Minimal", "status": "new"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["hypothesis"] == ""


def test_list_manual_tests_returns_created(client, auth_headers, program_id):
    client.post(f"/programs/{program_id}/manual-tests", json=_TEST, headers=auth_headers)
    res = client.get(f"/programs/{program_id}/manual-tests", headers=auth_headers)
    assert res.status_code == 200
    tests = res.json()["manual_tests"]
    assert any(t["title"] == _TEST["title"] for t in tests)


def test_list_manual_tests_pagination(client, auth_headers, program_id):
    for i in range(3):
        client.post(f"/programs/{program_id}/manual-tests", json={"title": f"Test {i}", "status": "new"}, headers=auth_headers)
    res = client.get(f"/programs/{program_id}/manual-tests?limit=2&offset=0", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["manual_tests"]) <= 2
    assert data["total"] >= 3


def test_update_manual_test(client, auth_headers, program_id):
    tid = client.post(f"/programs/{program_id}/manual-tests", json=_TEST, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/manual-tests/{tid}", json={"status": "validated"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "validated"


def test_update_manual_test_partial(client, auth_headers, program_id):
    tid = client.post(f"/programs/{program_id}/manual-tests", json=_TEST, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/manual-tests/{tid}", json={"evidence": "Updated evidence"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["evidence"] == "Updated evidence"
    assert data["title"] == _TEST["title"]


def test_update_nonexistent_manual_test_returns_404(client, auth_headers, program_id):
    res = client.patch(f"/programs/{program_id}/manual-tests/nonexistent", json={"status": "validated"}, headers=auth_headers)
    assert res.status_code == 404


def test_delete_manual_test(client, auth_headers, program_id):
    tid = client.post(f"/programs/{program_id}/manual-tests", json=_TEST, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/manual-tests/{tid}", headers=auth_headers)
    assert res.status_code == 200


def test_delete_nonexistent_manual_test_returns_404(client, auth_headers, program_id):
    res = client.delete(f"/programs/{program_id}/manual-tests/nonexistent", headers=auth_headers)
    assert res.status_code == 404


# BOLA checks

def test_add_manual_test_to_other_users_program_returns_404(client, other_headers, program_id):
    res = client.post(f"/programs/{program_id}/manual-tests", json=_TEST, headers=other_headers)
    assert res.status_code == 404


def test_list_manual_tests_for_other_users_program_returns_404(client, other_headers, program_id):
    res = client.get(f"/programs/{program_id}/manual-tests", headers=other_headers)
    assert res.status_code == 404


def test_update_manual_test_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    tid = client.post(f"/programs/{program_id}/manual-tests", json=_TEST, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/manual-tests/{tid}", json={"status": "validated"}, headers=other_headers)
    assert res.status_code == 404


def test_delete_manual_test_from_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    tid = client.post(f"/programs/{program_id}/manual-tests", json=_TEST, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/manual-tests/{tid}", headers=other_headers)
    assert res.status_code == 404


# Auth checks

def test_list_manual_tests_unauthorized(client, program_id):
    res = client.get(f"/programs/{program_id}/manual-tests")
    assert res.status_code == 401


def test_add_manual_test_unauthorized(client, program_id):
    res = client.post(f"/programs/{program_id}/manual-tests", json=_TEST)
    assert res.status_code == 401
