"""Opt-in public Distribution queue contract; ASGI only, no tool execution.

Set NM2_DISTRIBUTION_SOURCE and NM2_RUNNER_SOURCE to explicit checkout directories.
This checks queue payloads and pure plan compilation, not TLS/owner provenance.
"""

import importlib.util
import os
from pathlib import Path

import pytest


def test_distribution_queue_uses_supported_flat_config_and_separate_review_plan(
    client, auth_headers, monkeypatch
):
    distribution = os.environ.get("NM2_DISTRIBUTION_SOURCE")
    runner = os.environ.get("NM2_RUNNER_SOURCE")
    if not distribution:
        pytest.skip("explicit Distribution source directory required")
    assert runner, "NM2_RUNNER_SOURCE is required with opted-in Distribution source"
    distribution, runner = Path(distribution), Path(runner)
    assert distribution.is_absolute() and runner.is_absolute()
    source = distribution / "tests" / "nm2_worker_acceptance.py"
    assert (
        source.is_file()
        and (runner / "vardrrunner" / "authorization" / "plan.py").is_file()
    )
    monkeypatch.syspath_prepend(str(distribution / "tests"))
    monkeypatch.syspath_prepend(str(runner))
    spec = importlib.util.spec_from_file_location(
        "nm2_public_distribution_queue", source
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def no_command(*args, **kwargs):
        pytest.fail("queue preparation must not invoke Docker or another process")

    monkeypatch.setattr(module, "command", no_command)

    class API:
        engagement_id = None

        def request(self, path, body=None, *, method=None, expected=200):
            response = client.request(
                method or ("POST" if body is not None else "GET"),
                path,
                headers=auth_headers,
                **({"json": body} if body is not None else {}),
            )
            assert response.status_code == expected, response.text
            reply = response.json()
            if path == "/engagements" and body is not None:
                self.engagement_id = reply["id"]
            return reply

    api = API()
    # Exercise the public method without invoking its unrelated Docker setup.
    fixture = module.Fixture.__new__(module.Fixture)
    fixture.api = api
    fixture.project = "vardrsec-nm2-asgiqueue"
    try:
        engagement, authorization, job_id, case = fixture.new_job("asgi-queue")
        assert engagement == api.engagement_id and authorization
        jobs = api.request(f"/engagements/{engagement}/jobs")["jobs"]
        job = next(row for row in jobs if row["id"] == job_id)
        assert job["status"] == "pending"
        assert job["authorization_contract_required"] is True
        assert job["config"] == {"test_case_id": case["id"], "timeout": 20}
        from vardrrunner.authorization.plan import compile_gate_plan

        assert (
            Path(compile_gate_plan.__code__.co_filename).resolve()
            == (runner / "vardrrunner" / "authorization" / "plan.py").resolve()
        )
        plan = compile_gate_plan(case["spec"], module.EXECUTION, tool_sha256="a" * 64)
        assert plan["execution"] == {
            "timeout_seconds": 20,
            "max_response_bytes": 65536,
            "allow_private_targets": True,
        }
        assert "execution" not in job["config"]
        assert len(plan["dispatches"]) == 5
    finally:
        if api.engagement_id is not None:
            response = client.delete(
                f"/engagements/{api.engagement_id}", headers=auth_headers
            )
            assert response.status_code == 200, response.text
