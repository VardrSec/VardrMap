"""Report CRUD and BOLA/IDOR ownership checks."""

_REPORT = {"title": "XSS in login form", "summary": "Reflected XSS via username field", "steps": "1. Submit <script>", "impact": "Session hijack", "remediation": "Escape output", "cwe": "CWE-79", "cvss": "6.1", "status": "draft"}


def test_list_reports_empty(client, auth_headers, program_id):
    res = client.get(f"/programs/{program_id}/reports", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data["reports"], list)
    assert "total" in data


def test_add_report(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/reports", json=_REPORT, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == _REPORT["title"]
    assert data["status"] == "draft"
    assert "id" in data


def test_add_report_minimal(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/reports", json={"title": "Minimal report", "status": "draft"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["summary"] == ""
    assert data["cwe"] == ""


def test_add_report_with_finding_id(client, auth_headers, program_id):
    finding = client.post(f"/programs/{program_id}/findings", json={"title": "XSS", "severity": "high", "asset": "example.com", "status": "new"}, headers=auth_headers).json()
    res = client.post(f"/programs/{program_id}/reports", json={**_REPORT, "finding_id": finding["id"]}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["finding_id"] == finding["id"]


def test_list_reports_returns_created(client, auth_headers, program_id):
    client.post(f"/programs/{program_id}/reports", json=_REPORT, headers=auth_headers)
    res = client.get(f"/programs/{program_id}/reports", headers=auth_headers)
    assert res.status_code == 200
    assert any(r["title"] == _REPORT["title"] for r in res.json()["reports"])


def test_list_reports_pagination(client, auth_headers, program_id):
    for i in range(3):
        client.post(f"/programs/{program_id}/reports", json={"title": f"Report {i}", "status": "draft"}, headers=auth_headers)
    res = client.get(f"/programs/{program_id}/reports?limit=2&offset=0", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["reports"]) <= 2
    assert data["total"] >= 3


def test_update_report(client, auth_headers, program_id):
    rid = client.post(f"/programs/{program_id}/reports", json=_REPORT, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/reports/{rid}", json={"status": "submitted"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "submitted"


def test_update_report_partial(client, auth_headers, program_id):
    rid = client.post(f"/programs/{program_id}/reports", json=_REPORT, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/reports/{rid}", json={"cvss": "9.8"}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["cvss"] == "9.8"
    assert data["title"] == _REPORT["title"]


def test_update_nonexistent_report_returns_404(client, auth_headers, program_id):
    res = client.patch(f"/programs/{program_id}/reports/nonexistent", json={"status": "submitted"}, headers=auth_headers)
    assert res.status_code == 404


def test_delete_report(client, auth_headers, program_id):
    rid = client.post(f"/programs/{program_id}/reports", json=_REPORT, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/reports/{rid}", headers=auth_headers)
    assert res.status_code == 200


def test_delete_nonexistent_report_returns_404(client, auth_headers, program_id):
    res = client.delete(f"/programs/{program_id}/reports/nonexistent", headers=auth_headers)
    assert res.status_code == 404


# BOLA checks

def test_add_report_to_other_users_program_returns_404(client, other_headers, program_id):
    res = client.post(f"/programs/{program_id}/reports", json=_REPORT, headers=other_headers)
    assert res.status_code == 404


def test_list_reports_for_other_users_program_returns_404(client, other_headers, program_id):
    res = client.get(f"/programs/{program_id}/reports", headers=other_headers)
    assert res.status_code == 404


def test_update_report_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    rid = client.post(f"/programs/{program_id}/reports", json=_REPORT, headers=auth_headers).json()["id"]
    res = client.patch(f"/programs/{program_id}/reports/{rid}", json={"status": "submitted"}, headers=other_headers)
    assert res.status_code == 404


def test_delete_report_from_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    rid = client.post(f"/programs/{program_id}/reports", json=_REPORT, headers=auth_headers).json()["id"]
    res = client.delete(f"/programs/{program_id}/reports/{rid}", headers=other_headers)
    assert res.status_code == 404


# Auth checks

def test_list_reports_unauthorized(client, program_id):
    res = client.get(f"/programs/{program_id}/reports")
    assert res.status_code == 401


def test_add_report_unauthorized(client, program_id):
    res = client.post(f"/programs/{program_id}/reports", json=_REPORT)
    assert res.status_code == 401
