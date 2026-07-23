"""Tests for POST /programs/{id}/scans/triage — AI triage over raw scan items."""
import io
import json
import os
import sys

import pytest


def _seed_scans(client, auth_headers, program_id, count=2):
    lines = "\n".join(
        f'{{"template-id":"sqli-{i}","info":{{"name":"SQL Injection {i}","severity":"high"}},"host":"http://example{i}.com","matched-at":"http://example{i}.com/login"}}'
        for i in range(count)
    )
    res = client.post(
        f"/programs/{program_id}/imports",
        files={"file": ("nuclei.jsonl", io.BytesIO(lines.encode()), "application/json")},
        data={"tool_type": "nuclei"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    return client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"]


def _mock_anthropic(response_text: str):
    mock_content = MagicMockText(response_text)
    mock_msg = type("M", (), {"content": [mock_content]})()
    instance = type("C", (), {})()
    instance.messages = type("Msgs", (), {"create": lambda self, **kw: mock_msg})()
    module = type("Mod", (), {})()
    module.Anthropic = lambda api_key=None: instance
    return module


class MagicMockText:
    def __init__(self, text):
        self.text = text


def _call_triage(client, headers, program_id, response_text, ids=None):
    module = _mock_anthropic(response_text)
    original = sys.modules.get("anthropic")
    sys.modules["anthropic"] = module
    old_key = os.environ.get("ANTHROPIC_API_KEY", "")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        return client.post(
            f"/programs/{program_id}/scans/triage",
            json={"ids": ids or []},
            headers=headers,
        )
    finally:
        os.environ["ANTHROPIC_API_KEY"] = old_key
        if original is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = original


def test_triage_requires_auth(client, program_id):
    res = client.post(f"/programs/{program_id}/scans/triage", json={"ids": []})
    assert res.status_code == 401


def test_triage_bola_404(client, other_headers, program_id):
    res = client.post(f"/programs/{program_id}/scans/triage", json={"ids": []}, headers=other_headers)
    assert res.status_code == 404


def test_triage_empty_returns_empty_without_calling_ai(client, auth_headers, program_id):
    # No scan items and no key set — should short-circuit to [] before needing the key.
    old_key = os.environ.get("ANTHROPIC_API_KEY", "")
    os.environ["ANTHROPIC_API_KEY"] = ""
    res = client.post(f"/programs/{program_id}/scans/triage", json={"ids": []}, headers=auth_headers)
    os.environ["ANTHROPIC_API_KEY"] = old_key
    assert res.status_code == 200
    assert res.json()["triage"] == []


def test_triage_503_when_no_key(client, auth_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=1)
    old_key = os.environ.get("ANTHROPIC_API_KEY", "")
    os.environ["ANTHROPIC_API_KEY"] = ""
    res = client.post(f"/programs/{program_id}/scans/triage", json={"ids": []}, headers=auth_headers)
    os.environ["ANTHROPIC_API_KEY"] = old_key
    assert res.status_code == 503


def test_triage_success_ranks_items(client, auth_headers, program_id):
    scans = _seed_scans(client, auth_headers, program_id, count=2)
    payload = json.dumps([
        {"id": scans[0]["id"], "priority": "high", "false_positive": False, "rationale": "Real SQLi."},
        {"id": scans[1]["id"], "priority": "noise", "false_positive": True, "rationale": "Version banner only."},
    ])
    res = _call_triage(client, auth_headers, program_id, payload)
    assert res.status_code == 200, res.text
    triage = res.json()["triage"]
    assert len(triage) == 2
    by_id = {t["id"]: t for t in triage}
    assert by_id[scans[0]["id"]]["priority"] == "high"
    assert by_id[scans[1]["id"]]["false_positive"] is True


def test_triage_drops_foreign_ids_from_model(client, auth_headers, program_id):
    scans = _seed_scans(client, auth_headers, program_id, count=1)
    # Model hallucinates an id we never sent — it must be filtered out.
    payload = json.dumps([
        {"id": scans[0]["id"], "priority": "high", "false_positive": False, "rationale": "ok"},
        {"id": "smuggled-id", "priority": "high", "false_positive": False, "rationale": "evil"},
    ])
    res = _call_triage(client, auth_headers, program_id, payload)
    assert res.status_code == 200
    ids = {t["id"] for t in res.json()["triage"]}
    assert ids == {scans[0]["id"]}


def test_triage_non_json_returns_502(client, auth_headers, program_id):
    _seed_scans(client, auth_headers, program_id, count=1)
    res = _call_triage(client, auth_headers, program_id, "not json at all")
    assert res.status_code == 502
