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


def test_httpx_dedup_skips_seen_urls(client, auth_headers, program_id):
    lines = "\n".join([
        json.dumps({"url": "https://dedup-seen.example.com", "host": "dedup-seen.example.com", "status-code": 200}),
    ])
    # First import — new
    _upload(client, auth_headers, program_id, lines.encode(), "httpx.jsonl", "httpx", "application/x-ndjson")

    # Second import of same URL — should be deduplicated
    res = _upload(client, auth_headers, program_id, lines.encode(), "httpx.jsonl", "httpx", "application/x-ndjson")
    assert res.status_code == 200
    data = res.json()
    assert data["new_count"] == 0
    assert data["imported_count"] == 0


def test_httpx_dedup_partial_overlap(client, auth_headers, program_id):
    existing_line = json.dumps({"url": "https://dedup-old.example.com", "host": "dedup-old.example.com", "status-code": 200})
    new_line = json.dumps({"url": "https://dedup-new.example.com", "host": "dedup-new.example.com", "status-code": 200})

    # Seed existing
    _upload(client, auth_headers, program_id, existing_line.encode(), "httpx.json", "httpx", "application/json")

    # Import mix — only the new URL should count
    combined = "\n".join([existing_line, new_line])
    res = _upload(client, auth_headers, program_id, combined.encode(), "httpx.jsonl", "httpx", "application/x-ndjson")
    assert res.status_code == 200
    data = res.json()
    assert data["new_count"] == 1
    assert data["imported_count"] == 1


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
