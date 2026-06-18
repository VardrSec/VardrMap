"""File import endpoint — extension, size, and JSON validation; tool-specific parsing."""
import io
import json


def _upload(client, auth_headers, program_id, content: bytes, filename: str, tool_type: str, content_type: str = "application/json"):
    return client.post(
        f"/programs/{program_id}/imports",
        data={"tool_type": tool_type},
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=auth_headers,
    )


def _httpx(client, auth_headers, program_id, items):
    return _upload(client, auth_headers, program_id, json.dumps(items).encode(), "httpx.json", "httpx")


def test_httpx_enriches_existing_host_not_duplicate(client, auth_headers, program_id):
    # Subfinder-style discovery: a bare host with no live data.
    r1 = _httpx(client, auth_headers, program_id, [{"url": "sub.example.com"}])
    assert r1.status_code == 200
    assert r1.json()["new_count"] == 1
    assert r1.json()["updated_count"] == 0
    # httpx live probe of the SAME host (full URL + live fields) — enrich, not duplicate.
    r2 = _httpx(client, auth_headers, program_id,
                [{"url": "https://sub.example.com", "status-code": 200, "title": "Login", "webserver": "nginx"}])
    body = r2.json()
    assert body["new_count"] == 0
    assert body["updated_count"] == 1
    assert body["program"]["recon_count"] == 1  # one asset, enriched — not two rows


def test_httpx_new_host_inserts(client, auth_headers, program_id):
    r = _httpx(client, auth_headers, program_id, [{"url": "https://fresh.example.com", "status-code": 200}])
    assert r.json()["new_count"] == 1
    assert r.json()["updated_count"] == 0


def test_ffuf_paths_not_host_merged(client, auth_headers, program_id):
    payload = json.dumps([
        {"url": "https://example.com/admin", "status": 200},
        {"url": "https://example.com/login", "status": 200},
    ]).encode()
    r = _upload(client, auth_headers, program_id, payload, "ffuf.json", "ffuf")
    assert r.json()["new_count"] == 2  # ffuf paths are distinct assets, not collapsed by host


def test_bad_extension_rejected(client, auth_headers, program_id):
    res = _upload(client, auth_headers, program_id, b'[]', "results.csv", "nuclei")
    assert res.status_code == 400


def test_file_too_large_rejected(client, auth_headers, program_id):
    # MAX_UPLOAD_BYTES defaults to 2 MB; send 2 MB + 1 byte
    big = b"x" * (2 * 1024 * 1024 + 1)
    res = _upload(client, auth_headers, program_id, big, "big.json", "nuclei")
    assert res.status_code == 413


def test_empty_file_rejected(client, auth_headers, program_id):
    res = _upload(client, auth_headers, program_id, b"", "empty.json", "nuclei")
    assert res.status_code == 400


def test_invalid_json_rejected(client, auth_headers, program_id):
    res = _upload(client, auth_headers, program_id, b"not json at all", "bad.json", "nuclei")
    assert res.status_code == 400


def test_nuclei_import(client, auth_headers, program_id):
    payload = json.dumps([{
        "template-id": "xss-001",
        "info": {
            "name": "Reflected XSS",
            "severity": "high",
            "description": "XSS via query param",
            "classification": {"cwe-id": ["CWE-79"], "cvss-score": 6.1},
        },
        "matched-at": "https://example.com/search?q=test",
        "type": "http",
    }]).encode()
    res = _upload(client, auth_headers, program_id, payload, "nuclei.json", "nuclei")
    assert res.status_code == 200
    assert res.json()["import_record"]["imported_count"] == 1


def test_httpx_jsonl_import(client, auth_headers, program_id):
    lines = "\n".join([
        json.dumps({"url": "https://example.com", "host": "example.com", "status-code": 200, "title": "Home", "webserver": "nginx", "tech": ["React"]}),
        json.dumps({"url": "https://api.example.com", "host": "api.example.com", "status-code": 200, "title": "API", "webserver": "nginx", "tech": []}),
    ])
    res = _upload(client, auth_headers, program_id, lines.encode(), "httpx.jsonl", "httpx", "application/x-ndjson")
    assert res.status_code == 200
    assert res.json()["import_record"]["imported_count"] == 2


def test_ffuf_import(client, auth_headers, program_id):
    payload = json.dumps({
        "results": [
            {"url": "https://example.com/admin", "status": 200, "length": 1234, "words": 50, "lines": 30, "content-type": "text/html"},
            {"url": "https://example.com/login", "status": 200, "length": 800, "words": 30, "lines": 20, "content-type": "text/html"},
        ]
    }).encode()
    res = _upload(client, auth_headers, program_id, payload, "ffuf.json", "ffuf")
    assert res.status_code == 200
    assert res.json()["import_record"]["imported_count"] == 2


def test_import_into_other_users_program_returns_404(client, other_headers, program_id):
    payload = json.dumps([]).encode()
    res = _upload(client, other_headers, program_id, payload, "nuclei.json", "nuclei")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Recon deduplication
# ---------------------------------------------------------------------------

def test_httpx_dedup_new_items(client, auth_headers, program_id):
    lines = "\n".join([
        json.dumps({"url": "https://dedup-a.example.com", "host": "dedup-a.example.com", "status-code": 200}),
        json.dumps({"url": "https://dedup-b.example.com", "host": "dedup-b.example.com", "status-code": 200}),
    ])
    res = _upload(client, auth_headers, program_id, lines.encode(), "httpx.jsonl", "httpx", "application/x-ndjson")
    assert res.status_code == 200
    data = res.json()
    assert data["imported_count"] == 2
    assert data["new_count"] == 2


def test_httpx_reprobe_enriches_seen_host(client, auth_headers, program_id):
    line = json.dumps({"url": "https://dedup-seen.example.com", "host": "dedup-seen.example.com", "status-code": 200})
    # First import — new
    _upload(client, auth_headers, program_id, line.encode(), "httpx.jsonl", "httpx", "application/x-ndjson")

    # Second import of the same host — enriched in place, not duplicated.
    res = _upload(client, auth_headers, program_id, line.encode(), "httpx.jsonl", "httpx", "application/x-ndjson")
    assert res.status_code == 200
    data = res.json()
    assert data["new_count"] == 0
    assert data["updated_count"] == 1
    assert data["imported_count"] == 1


def test_httpx_dedup_partial_overlap(client, auth_headers, program_id):
    existing_line = json.dumps({"url": "https://dedup-old.example.com", "host": "dedup-old.example.com", "status-code": 200})
    new_line = json.dumps({"url": "https://dedup-new.example.com", "host": "dedup-new.example.com", "status-code": 200})

    # Seed existing
    _upload(client, auth_headers, program_id, existing_line.encode(), "httpx.json", "httpx", "application/json")

    # Import mix — the new host is inserted, the seen host is enriched.
    combined = "\n".join([existing_line, new_line])
    res = _upload(client, auth_headers, program_id, combined.encode(), "httpx.jsonl", "httpx", "application/x-ndjson")
    assert res.status_code == 200
    data = res.json()
    assert data["new_count"] == 1       # dedup-new inserted
    assert data["updated_count"] == 1   # dedup-old enriched in place
    assert data["imported_count"] == 2


def test_nuclei_import_returns_new_count_zero(client, auth_headers, program_id):
    # nuclei doesn't use recon dedup — new_count is always 0
    payload = json.dumps([{
        "template-id": "sqli-001",
        "info": {"name": "SQLi", "severity": "critical"},
        "matched-at": "https://example.com/login",
    }]).encode()
    res = _upload(client, auth_headers, program_id, payload, "nuclei.json", "nuclei")
    assert res.status_code == 200
    assert res.json()["new_count"] == 0
    assert res.json()["imported_count"] == 1
