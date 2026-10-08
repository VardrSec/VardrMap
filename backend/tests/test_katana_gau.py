"""katana and gau: job types, queue-time config validation, and recon import."""
import io
import json

import pytest

# Mirrors a real katana 1.8.0 result line: full raw request/response, bodies included.
KATANA_RAW = {
    "timestamp": "2026-10-08T03:27:47-05:00",
    "request": {
        "method": "GET",
        "endpoint": "https://app.example.com/admin/login",
        "raw": "GET /admin/login HTTP/1.1\r\nHost: app.example.com\r\n\r\n",
    },
    "response": {
        "status_code": 200,
        "headers": {"Content-Type": "text/html"},
        "body": "<html>secret page content</html>",
        "content_length": 32,
        "raw": "HTTP/1.1 200 OK\r\n\r\n<html>secret page content</html>",
    },
}


def _jsonl(rows) -> bytes:
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode()


def _upload(client, headers, program_id, tool_type, rows):
    return client.post(
        f"/programs/{program_id}/imports",
        data={"tool_type": tool_type},
        files={"file": (f"{tool_type}.jsonl", io.BytesIO(_jsonl(rows)), "application/json")},
        headers=headers,
    )


def _recon(client, headers, program_id, source):
    rows = client.get(f"/programs/{program_id}/recon", headers=headers).json()["recon"]
    return [r for r in rows if r["source"] == source]


def _create_job(client, program_id, headers, **body):
    return client.post(
        f"/programs/{program_id}/jobs",
        json={"target_source": "scope", **body},
        headers=headers,
    )


# ── job types ───────────────────────────────────────────────────────────────


def test_katana_job_accepted(client, program_id, auth_headers):
    res = _create_job(
        client, program_id, auth_headers, tool_type="katana", target_source="recon",
        config={"depth": 3, "js_crawl": "true", "limit": 50},
    )
    assert res.status_code == 200
    assert res.json()["tool_type"] == "katana"


def test_gau_job_accepted(client, program_id, auth_headers):
    res = _create_job(
        client, program_id, auth_headers, tool_type="gau",
        config={"subs": False, "providers": "otx,wayback"},
    )
    assert res.status_code == 200
    assert res.json()["tool_type"] == "gau"


@pytest.mark.parametrize(
    "tool, config, field",
    [
        ("katana", {"depth": 0}, "depth"),
        ("katana", {"depth": 11}, "depth"),
        ("katana", {"js_crawl": "yes"}, "js_crawl"),
        ("katana", {"severity": "high"}, "unknown config keys"),
        ("gau", {"providers": "otx,notaprovider"}, "providers"),
        ("gau", {"providers": ["wayback", "evil"]}, "providers"),
        ("gau", {"subs": "maybe"}, "subs"),
        ("gau", {"timeout": 0}, "timeout"),
        ("gau", {"depth": 3}, "unknown config keys"),
    ],
)
def test_bad_configs_refused_at_queue_time(client, program_id, auth_headers, tool, config, field):
    """Bounds mirror VardrRunner's, so a bad value never reaches the operator's machine."""
    res = _create_job(client, program_id, auth_headers, tool_type=tool, config=config)
    assert res.status_code == 400
    assert field in res.text


def test_job_on_other_users_engagement_is_404(client, program_id, other_headers):
    res = _create_job(client, program_id, other_headers, tool_type="gau")
    assert res.status_code == 404


# ── katana import ───────────────────────────────────────────────────────────


def test_katana_compact_records_import_as_recon(client, auth_headers, program_id):
    """The compact shape VardrRunner uploads."""
    res = _upload(client, auth_headers, program_id, "katana", [{
        "url": "https://app.example.com/api/v1/users", "method": "GET", "status_code": 404,
        "content_length": 460, "content_type": "text/html;charset=utf-8", "source": "katana",
    }])
    assert res.status_code == 200
    assert res.json()["import_record"]["imported_count"] == 1
    [row] = _recon(client, auth_headers, program_id, "katana")
    assert row["url"] == "https://app.example.com/api/v1/users"
    assert row["host"] == "app.example.com"
    assert row["path"] == "/api/v1/users"
    assert row["status_code"] == 404
    assert row["length"] == 460
    assert row["content_type"] == "text/html;charset=utf-8"


def test_katana_raw_output_imports_without_bodies(client, auth_headers, program_id):
    """A file exported straight from katana also imports; bodies are never stored."""
    res = _upload(client, auth_headers, program_id, "katana", [KATANA_RAW])
    assert res.status_code == 200
    [row] = _recon(client, auth_headers, program_id, "katana")
    assert row["url"] == "https://app.example.com/admin/login"
    assert row["status_code"] == 200 and row["content_type"] == "text/html"
    assert "secret page content" not in json.dumps(row)


def test_katana_import_dedupes_within_and_across_uploads(client, auth_headers, program_id):
    rows = [KATANA_RAW, KATANA_RAW, {"url": "https://app.example.com/other"}]
    assert _upload(client, auth_headers, program_id, "katana", rows).json()["new_count"] == 2
    assert _upload(client, auth_headers, program_id, "katana", rows).json()["new_count"] == 0
    assert len(_recon(client, auth_headers, program_id, "katana")) == 2


# ── gau import ──────────────────────────────────────────────────────────────


def test_gau_import_keeps_only_web_urls(client, auth_headers, program_id):
    rows = [
        {"url": "https://example.com/reset?token=abc"},
        {"url": "http://old.example.com/page.php"},
        {"url": "https://example.com/reset?token=abc"},  # duplicate
        {"url": "mailto:someone@example.com"},
        {"url": "javascript:alert(1)"},
        {"url": "not a url"},
        {"url": ""},
        {"other": "field"},
    ]
    res = _upload(client, auth_headers, program_id, "gau", rows)
    assert res.status_code == 200
    assert res.json()["new_count"] == 2
    urls = sorted(r["url"] for r in _recon(client, auth_headers, program_id, "gau"))
    assert urls == ["http://old.example.com/page.php", "https://example.com/reset?token=abc"]


def test_gau_and_katana_are_tracked_as_separate_sources(client, auth_headers, program_id):
    url = "https://app.example.com/admin/login"
    _upload(client, auth_headers, program_id, "gau", [{"url": url}])
    _upload(client, auth_headers, program_id, "katana", [{"url": url}])
    assert len(_recon(client, auth_headers, program_id, "gau")) == 1
    assert len(_recon(client, auth_headers, program_id, "katana")) == 1


def test_gau_import_html_in_url_is_stripped(client, auth_headers, program_id):
    _upload(client, auth_headers, program_id, "gau", [{"url": "https://example.com/<script>x</script>"}])
    [row] = _recon(client, auth_headers, program_id, "gau")
    assert "<script>" not in row["url"]


def test_import_into_other_users_engagement_is_404(client, other_headers, program_id):
    res = _upload(client, other_headers, program_id, "gau", [{"url": "https://example.com/"}])
    assert res.status_code == 404


def test_unknown_tool_type_still_rejected(client, auth_headers, program_id):
    res = _upload(client, auth_headers, program_id, "waybackurls", [{"url": "https://example.com/"}])
    assert res.status_code == 422
