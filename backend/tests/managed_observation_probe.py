"""Test-only authenticated observation through the production Runner parser."""

import hashlib
import json

from sqlalchemy.orm import Session

from models import Engagement, JobExecution, ManagedApproval
from tests.test_managed_issuance import KEY, RUNNER


def flow(h, transport=None, *, kind):
    from vardrrunner.authorization import observations
    from vardrrunner.authorization.codec import digest, encoded

    probe = h.probe(transport)
    root = {
        "origin": probe.origin,
        "job_id": "job-1",
        "runner_id": RUNNER,
        "plan_sha256": digest(encoded(h.review["plan"])),
        "case_sha256": h.review["plan"]["case_hash"],
        "association_sha256": digest(
            encoded(
                {
                    "origin": probe.origin,
                    "runner_id": RUNNER,
                    "principal_sha256": hashlib.sha256(("Bearer " + KEY).encode()).hexdigest(),
                }
            )
        ),
    }
    body = {k: v for k, v in root.items() if k != "job_id"}
    absent = probe.post("/fixture/observe", body)
    observations.validate(absent, root, {"contract": None})
    assert absent["claim"] is None
    if kind == "result":
        from tests.managed_result_probe import flow as complete
    else:
        from tests.managed_stop_probe import flow as complete
    complete(h, transport)
    with Session(h.s["engine"]) as db:
        before = db.get(JobExecution, "job-1").expires_at
    reply = probe.post("/fixture/observe", body)
    observations.validate(reply, root, {"contract": None})
    assert reply["claim"]["consumed"] is True
    assert reply["capacity_reserved"] is False
    assert reply["completion" if kind == "result" else "stop"] is not None
    assert not any(
        word in json.dumps(reply) for word in ('"token"', '"lease_seconds"', '"envelope"')
    )
    with Session(h.s["engine"]) as db:
        assert db.get(JobExecution, "job-1").expires_at == before
        assert db.query(ManagedApproval).one().issued == 1
        assert db.get(Engagement, "eng-1").duration_allocated == 30
