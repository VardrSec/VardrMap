"""Provider calls redact credentials and never echo provider exception details."""
import sys
from unittest.mock import MagicMock

import pytest
from db import get_db
from main import app
from models import Finding, ScanItem


@pytest.mark.parametrize("kind", ["finding", "scan"])
@pytest.mark.parametrize("failure", [False, True])
def test_ai_provider_boundary(client, auth_headers, program_id, monkeypatch, kind, failure):
    secret = "private-provider-test-secret"
    session = next(app.dependency_overrides[get_db]())
    if kind == "finding":
        row = Finding(program_id=program_id, title="Test", summary=f"Authorization: Bearer {secret}")
    else:
        row = ScanItem(program_id=program_id, title="Test", description=f"Authorization: Bearer {secret}")
    session.add(row)
    session.commit()
    session.refresh(row)
    session.close()
    module = MagicMock()
    provider = module.Anthropic.return_value
    if failure:
        provider.messages.create.side_effect = RuntimeError(secret)
    else:
        provider.messages.create.return_value.content[0].text = "{}" if kind == "finding" else "[]"
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    url = (f"/engagements/{program_id}/findings/{row.id}/suggest" if kind == "finding"
           else f"/engagements/{program_id}/scans/triage")
    response = client.post(url, headers=auth_headers, json={"ids": [row.id]})
    assert response.status_code == (502 if failure else 200), response.text
    content = provider.messages.create.call_args.kwargs["messages"][0]["content"]
    assert secret not in content
    assert secret not in response.text
    assert "[REDACTED]" in content
