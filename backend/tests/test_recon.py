"""Recon item listing, filtering, pagination, and BOLA/IDOR ownership checks."""
import io


def _seed_recon(client, auth_headers, program_id, count=2):
    """Import httpx JSONL to seed recon items for a program."""
    lines = "\n".join(
        f'{{"url":"http://sub{i}.example.com","host":"sub{i}.example.com","status-code":{200 + i},"title":"Site {i}","webserver":"nginx"}}'
        for i in range(count)
    )
    content = lines.encode()
    res = client.post(
        f"/programs/{program_id}/imports",
        files={"file": ("httpx.jsonl", io.BytesIO(content), "application/json")},
        data={"tool_type": "httpx"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    return res.json()


def test_list_recon_empty(client, auth_headers, program_id):
    res = client.get(f"/programs/{program_id}/recon", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data["recon"], list)
    assert "total" in data


def test_list_recon_returns_seeded(client, auth_headers, program_id):
    _seed_recon(client, auth_headers, program_id, count=2)
    res = client.get(f"/programs/{program_id}/recon", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 2


def test_list_recon_search_by_host(client, auth_headers, program_id):
    _seed_recon(client, auth_headers, program_id, count=2)
    res = client.get(f"/programs/{program_id}/recon?search=sub0", headers=auth_headers)
    assert res.status_code == 200
    items = res.json()["recon"]
    assert all("sub0" in (r.get("host") or r.get("url") or "") for r in items)


def test_list_recon_search_no_match(client, auth_headers, program_id):
    _seed_recon(client, auth_headers, program_id, count=2)
    res = client.get(f"/programs/{program_id}/recon?search=zzznomatch", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 0


def test_list_recon_status_code_filter(client, auth_headers, program_id):
    _seed_recon(client, auth_headers, program_id, count=2)
    res = client.get(f"/programs/{program_id}/recon?status_code=200", headers=auth_headers)
    assert res.status_code == 200
    items = res.json()["recon"]
    assert all(r["status_code"] == 200 for r in items)


def test_list_recon_pagination(client, auth_headers, program_id):
    _seed_recon(client, auth_headers, program_id, count=3)
    res = client.get(f"/programs/{program_id}/recon?limit=2&offset=0", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["recon"]) <= 2
    assert data["total"] >= 3


def test_list_recon_offset(client, auth_headers, program_id):
    _seed_recon(client, auth_headers, program_id, count=3)
    all_items = client.get(f"/programs/{program_id}/recon?limit=100", headers=auth_headers).json()["recon"]
    page2 = client.get(f"/programs/{program_id}/recon?limit=2&offset=2", headers=auth_headers).json()["recon"]
    if len(all_items) >= 3:
        assert len(page2) >= 1


# BOLA checks

def test_list_recon_for_other_users_program_returns_404(client, other_headers, program_id):
    res = client.get(f"/programs/{program_id}/recon", headers=other_headers)
    assert res.status_code == 404


# Auth checks

def test_list_recon_unauthorized(client, program_id):
    res = client.get(f"/programs/{program_id}/recon")
    assert res.status_code == 401
