"""Tests for POST /programs/{id}/findings/{id}/suggest.

Coverage:
- 503 when ANTHROPIC_API_KEY is not set
- 404 for wrong engagement (BOLA)
- 404 for wrong finding
- 401 unauthorized
- 200 success with mocked Claude response
- 502 when Claude returns non-JSON
- 502 when Claude API raises an exception
"""
import json
import sys
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_program(client, headers):
    res = client.post("/programs", json={"name": "AI Test Engagement"}, headers=headers)
    assert res.status_code == 200
    return res.json()["id"]


def _create_finding(client, program_id, headers):
    res = client.post(
        f"/programs/{program_id}/findings",
        json={
            "title": "SQL Injection in /login",
            "severity": "high",
            "asset": "https://app.example.com/login",
            "summary": "Unsanitized input allows SQLi",
            "steps": "1. POST /login with ' OR 1=1 --",
            "status": "new",
        },
        headers=headers,
    )
    assert res.status_code == 200
    return res.json()["id"]


def _suggest_url(program_id, finding_id):
    return f"/programs/{program_id}/findings/{finding_id}/suggest"


def _make_mock_anthropic(response_text: str) -> MagicMock:
    """Return a mock anthropic module whose Anthropic().messages.create() returns response_text."""
    mock_content = MagicMock()
    mock_content.text = response_text
    mock_msg = MagicMock()
    mock_msg.content = [mock_content]
    mock_client_instance = MagicMock()
    mock_client_instance.messages.create.return_value = mock_msg
    mock_module = MagicMock()
    mock_module.Anthropic.return_value = mock_client_instance
    return mock_module, mock_client_instance


# ---------------------------------------------------------------------------
# Auth / BOLA
# ---------------------------------------------------------------------------

class TestSuggestAuth:
    def test_unauthorized_401(self, client, program_id, auth_headers):
        fid = _create_finding(client, program_id, auth_headers)
        res = client.post(_suggest_url(program_id, fid))
        assert res.status_code == 401

    def test_wrong_user_program_404(self, client, program_id, auth_headers, other_headers):
        fid = _create_finding(client, program_id, auth_headers)
        res = client.post(_suggest_url(program_id, fid), headers=other_headers)
        assert res.status_code == 404

    def test_wrong_finding_id_404(self, client, program_id, auth_headers):
        import os
        mock_mod, _ = _make_mock_anthropic('{"cvss":"","impact":"","remediation":""}')
        with pytest.MonkeyPatch().context() as m:
            m.setenv("ANTHROPIC_API_KEY", "test-key")
            original = sys.modules.get("anthropic")
            sys.modules["anthropic"] = mock_mod
            try:
                res = client.post(_suggest_url(program_id, "nonexistent-id"), headers=auth_headers)
            finally:
                if original is None:
                    sys.modules.pop("anthropic", None)
                else:
                    sys.modules["anthropic"] = original
        assert res.status_code == 404

    def test_finding_from_other_program_404(self, client, auth_headers):
        prog1 = _create_program(client, auth_headers)
        prog2 = _create_program(client, auth_headers)
        fid = _create_finding(client, prog1, auth_headers)
        mock_mod, _ = _make_mock_anthropic('{"cvss":"","impact":"","remediation":""}')
        original = sys.modules.get("anthropic")
        sys.modules["anthropic"] = mock_mod
        try:
            import os
            old_key = os.environ.get("ANTHROPIC_API_KEY", "")
            os.environ["ANTHROPIC_API_KEY"] = "test-key"
            res = client.post(_suggest_url(prog2, fid), headers=auth_headers)
            os.environ["ANTHROPIC_API_KEY"] = old_key
        finally:
            if original is None:
                sys.modules.pop("anthropic", None)
            else:
                sys.modules["anthropic"] = original
        assert res.status_code == 404
        client.delete(f"/programs/{prog1}", headers=auth_headers)
        client.delete(f"/programs/{prog2}", headers=auth_headers)


# ---------------------------------------------------------------------------
# Service availability
# ---------------------------------------------------------------------------

class TestSuggestServiceCheck:
    def test_503_when_no_api_key(self, client, program_id, auth_headers):
        fid = _create_finding(client, program_id, auth_headers)
        import os
        old_key = os.environ.get("ANTHROPIC_API_KEY", "")
        os.environ["ANTHROPIC_API_KEY"] = ""
        res = client.post(_suggest_url(program_id, fid), headers=auth_headers)
        os.environ["ANTHROPIC_API_KEY"] = old_key
        assert res.status_code == 503
        assert "ANTHROPIC_API_KEY" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

class TestSuggestSuccess:
    def _with_mock_key(self, client, url, headers, response_json: dict):
        mock_mod, mock_instance = _make_mock_anthropic(json.dumps(response_json))
        original = sys.modules.get("anthropic")
        sys.modules["anthropic"] = mock_mod
        import os
        old_key = os.environ.get("ANTHROPIC_API_KEY", "")
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            res = client.post(url, headers=headers)
        finally:
            os.environ["ANTHROPIC_API_KEY"] = old_key
            if original is None:
                sys.modules.pop("anthropic", None)
            else:
                sys.modules["anthropic"] = original
        return res, mock_instance

    def test_success_200(self, client, program_id, auth_headers):
        fid = _create_finding(client, program_id, auth_headers)
        suggestion = {"cvss": "7.5 (High)", "impact": "Data breach.", "remediation": "Use parameterized queries."}
        res, _ = self._with_mock_key(client, _suggest_url(program_id, fid), auth_headers, suggestion)
        assert res.status_code == 200
        data = res.json()
        assert data["cvss"] == "7.5 (High)"
        assert data["impact"] == "Data breach."
        assert data["remediation"] == "Use parameterized queries."

    def test_uses_haiku_model(self, client, program_id, auth_headers):
        fid = _create_finding(client, program_id, auth_headers)
        _, mock_instance = self._with_mock_key(
            client, _suggest_url(program_id, fid), auth_headers,
            {"cvss": "5.0", "impact": "x", "remediation": "y"},
        )
        call_kwargs = mock_instance.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_502_on_non_json_response(self, client, program_id, auth_headers):
        fid = _create_finding(client, program_id, auth_headers)
        mock_mod, _ = _make_mock_anthropic("Sorry, I cannot help.")
        original = sys.modules.get("anthropic")
        sys.modules["anthropic"] = mock_mod
        import os
        old_key = os.environ.get("ANTHROPIC_API_KEY", "")
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            res = client.post(_suggest_url(program_id, fid), headers=auth_headers)
        finally:
            os.environ["ANTHROPIC_API_KEY"] = old_key
            if original is None:
                sys.modules.pop("anthropic", None)
            else:
                sys.modules["anthropic"] = original
        assert res.status_code == 502
        assert "non-JSON" in res.json()["detail"]

    def test_502_on_api_exception(self, client, program_id, auth_headers):
        fid = _create_finding(client, program_id, auth_headers)
        mock_mod = MagicMock()
        mock_instance = MagicMock()
        mock_instance.messages.create.side_effect = RuntimeError("connection refused")
        mock_mod.Anthropic.return_value = mock_instance
        original = sys.modules.get("anthropic")
        sys.modules["anthropic"] = mock_mod
        import os
        old_key = os.environ.get("ANTHROPIC_API_KEY", "")
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            res = client.post(_suggest_url(program_id, fid), headers=auth_headers)
        finally:
            os.environ["ANTHROPIC_API_KEY"] = old_key
            if original is None:
                sys.modules.pop("anthropic", None)
            else:
                sys.modules["anthropic"] = original
        assert res.status_code == 502
        assert "connection refused" in res.json()["detail"]
