"""Scan item listing and status update, including BOLA/IDOR ownership checks."""
import io


def _seed_scans(client, auth_headers, program_id, count=2):
    """Import nuclei JSONL to seed scan items for an engagement."""
    lines = "\n".join(
        f'{{"template-id":"sqli-{i}","info":{{"name":"SQL Injection {i}","severity":"high"}},"host":"http://example{i}.com","matched-at":"http://example{i}.com/login"}}'
        for i in range(count)
    )
    content = lines.encode()
    res = client.post(
        f"/programs/{program_id}/imports",
        files={"file": ("nuclei.jsonl", io.BytesIO(content), "application/json")},
        data={"tool_type": "nuclei"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    return res.json()


def test_list_scans_empty(client, auth_headers, program_id):
    res = client.get(f"/programs/{program_id}/scans", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data["scans"], list)
    assert "total" in data


def test_list_scans_returns_seeded(client, auth_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=2)
    res = client.get(f"/programs/{program_id}/scans", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 2


def test_list_scans_status_filter(client, auth_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=2)
    res = client.get(f"/programs/{program_id}/scans?status=new", headers=auth_headers)
    assert res.status_code == 200
    scans = res.json()["scans"]
    assert all(s["status"] == "new" for s in scans)


def test_list_scans_pagination(client, auth_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=3)
    res = client.get(f"/programs/{program_id}/scans?limit=2&offset=0", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["scans"]) <= 2
    assert data["total"] >= 3


def test_update_scan_status(client, auth_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=1)
    scan_id = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"][-1]["id"]
    res = client.patch(f"/programs/{program_id}/scans/{scan_id}", json={"status": "reviewed"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "reviewed"


def test_update_nonexistent_scan_returns_404(client, auth_headers, program_id):
    res = client.patch(f"/programs/{program_id}/scans/nonexistent", json={"status": "reviewed"}, headers=auth_headers)
    assert res.status_code == 404


def test_bulk_update_scan_status(client, auth_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=2)
    scans = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"]
    ids = [s["id"] for s in scans[-2:]]
    res = client.post(f"/programs/{program_id}/scans/bulk-status", json={"ids": ids, "status": "reviewed"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["updated"] == len(ids)


def test_bulk_update_with_empty_ids_returns_422(client, auth_headers, program_id):
    res = client.post(f"/programs/{program_id}/scans/bulk-status", json={"ids": [], "status": "reviewed"}, headers=auth_headers)
    assert res.status_code == 422


# BOLA checks

def test_list_scans_for_other_users_program_returns_404(client, other_headers, program_id):
    res = client.get(f"/programs/{program_id}/scans", headers=other_headers)
    assert res.status_code == 404


def test_update_scan_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=1)
    scan_id = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"][-1]["id"]
    res = client.patch(f"/programs/{program_id}/scans/{scan_id}", json={"status": "reviewed"}, headers=other_headers)
    assert res.status_code == 404


def test_bulk_update_scans_in_other_users_program_returns_404(client, auth_headers, other_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=1)
    scan_id = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"][-1]["id"]
    res = client.post(f"/programs/{program_id}/scans/bulk-status", json={"ids": [scan_id], "status": "reviewed"}, headers=other_headers)
    assert res.status_code == 404


# Auth checks

def test_list_scans_unauthorized(client, program_id):
    res = client.get(f"/programs/{program_id}/scans")
    assert res.status_code == 401


def test_update_scan_unauthorized(client, auth_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=1)
    scan_id = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"][-1]["id"]
    res = client.patch(f"/programs/{program_id}/scans/{scan_id}", json={"status": "reviewed"})
    assert res.status_code == 401
