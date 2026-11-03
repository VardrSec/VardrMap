"""Test-only signed/owned stop receipt conformance; no native containment claim."""


import pytest
from sqlalchemy.orm import Session

from models import Engagement, JobExecution, ManagedApproval, ManagedStop


def flow(h, transport=None, *, wire=None, lost=False):
    from vardrrunner.authorization.codec import AuthorizationError, digest, encoded
    from vardrrunner.authorization.stops import CAUSES, check_receipt, stop_hash

    from managed_stops import CAUSES as SERVER_CAUSES

    assert CAUSES == SERVER_CAUSES
    probe = h.probe(transport)
    probe.claim(h.body)
    probe.reserve()
    probe.launch(lambda: None)  # Inert; absolutely no process or target dispatch.
    request = {**probe.request, "contract_sha256": digest(encoded(probe.envelope))}
    probe.post("/fixture/consume", request)
    binding = {
        **probe.binding,
        **{k: request[k] for k in ("contract_id", "attempt_id", "fence", "contract_sha256")},
    }
    expected = {
        "binding": encoded(binding).decode(),
        "outcome": "cancelled",
        "cause": "local_emergency_stop",
        "receipt_sha256": stop_hash(binding, "cancelled", "local_emergency_stop"),
    }
    if wire is not None and lost:
        wire.mode = "drop_stopped"
    report = {
        **request,
        "outcome": "cancelled",
        "cause": "local_emergency_stop",
        "termination_confirmed": True,
    }
    if lost:
        with pytest.raises(AuthorizationError):
            probe.post("/fixture/stopped", report)
    else:
        check_receipt(probe.post("/fixture/stopped", report), expected)
    observed = probe.post("/fixture/stop-status", request)
    check_receipt(observed["stop"], expected)
    assert observed["capacity_reserved"] is False and observed["execution_state"] == "cancelled"
    with Session(h.s["engine"]) as db:
        assert db.query(ManagedStop).count() == 1
        assert db.get(JobExecution, "job-1").capacity_reserved is False
        assert db.query(ManagedApproval).one().issued == 1
        assert (
            db.get(Engagement, "eng-1").targets_spent,
            db.get(Engagement, "eng-1").duration_allocated,
        ) == (1, 30)
