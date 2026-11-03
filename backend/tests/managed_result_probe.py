"""Test-only authenticated JSON receipt conformance; inert execution only."""

import json

import assessments
import pytest
from models import JobExecution, ManagedResult
from sqlalchemy.orm import Session


def flow(h, transport=None, *, wire=None, lost=None):
    from vardrrunner.authorization.codec import AuthorizationError, digest, encoded
    from vardrrunner.authorization.results import check_completion, check_result, receipt

    probe = h.probe(transport)
    probe.claim(h.body)
    probe.reserve()
    inert = []
    probe.launch(lambda: inert.append(True))
    assert inert == [True]
    request = {**probe.request, "contract_sha256": digest(encoded(probe.envelope))}
    probe.post("/fixture/consume", request)
    binding = {
        **probe.binding,
        **{k: request[k] for k in ("contract_id", "attempt_id", "fence", "contract_sha256")},
    }
    artifact = json.dumps(
        {
            "test_case_id": probe.case["id"],
            "case_hash": assessments.case_hash(probe.case),
            "executions": [],
            "findings": [],
        }
    )
    sha = digest(artifact.encode())
    record = {
        "binding": encoded(binding).decode(),
        "artifact_sha256": sha,
        "case_sha256": assessments.case_hash(probe.case),
        "receipt_sha256": receipt(binding, sha, assessments.case_hash(probe.case)),
        "outcome": "completed",
    }
    if wire is not None and lost == "result":
        wire.mode = "drop_result"
    if lost == "result":
        with pytest.raises(AuthorizationError):
            probe.post("/fixture/result", {**request, "artifact": artifact, "artifact_sha256": sha})
    else:
        ack = probe.post(
            "/fixture/result", {**request, "artifact": artifact, "artifact_sha256": sha}
        )
        check_result(ack, record)
        if wire is not None and lost == "finish":
            wire.mode = "drop_finish"
        completion = {
            **request,
            "receipt_sha256": record["receipt_sha256"],
            "outcome": "completed",
            "termination_confirmed": True,
        }
        if lost == "finish":
            with pytest.raises(AuthorizationError):
                probe.post("/fixture/finish", completion)
        else:
            check_completion(probe.post("/fixture/finish", completion), record)
    observed = probe.post("/fixture/inspect", request)
    check_result(observed["result"], record)
    if lost == "result":
        assert observed["completion"] is None and observed["capacity_reserved"] is True
    else:
        check_completion(observed["completion"], record)
        assert observed["capacity_reserved"] is False
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedResult).count() == 1
        assert db.get(JobExecution, "job-1").capacity_reserved is (lost == "result")
