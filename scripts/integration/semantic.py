"""Opt-in checks for the coordinated semantic evidence rollout, using real workers."""

import copy
import json


def run_semantic(
    *,
    check,
    req,
    base,
    queue,
    run_worker,
    outputs,
    job_row,
    state,
    target,
    results,
    tokens,
):
    initial_findings = req("GET", base + "/findings")["findings"]
    probes = []

    def record(name, condition):
        probes.append({"name": name, "passed": bool(condition)})
        check("Semantic: " + name, condition)

    def identity(name, secret, principal=None):
        return {
            "id": name,
            "credential": {"type": "bearer", "value_env": secret},
            "preflight": {
                "url": target + "/session",
                "expected_status": 200,
                "json_fields": {"user.id": principal or name},
            },
        }

    common = {
        "identities": [
            identity("owner", "LAB_OWNER_TOKEN"),
            identity("peer", "LAB_PEER_TOKEN"),
        ],
        "require_identity_preflight": True,
        "expected_access": [
            {"identity_id": "owner", "decision": "allow"},
            {"identity_id": "peer", "decision": "deny"},
        ],
        "resource": {"type": "fixture", "owner_identity": "owner"},
    }

    def execute(label, mode, spec):
        state["mode"] = mode
        mark = len(state["requests"])
        stored = req(
            "POST",
            base + "/test-cases/reviewed",
            {
                "reviewed": True,
                "cases": [{"name": label, "spec": spec}],
            },
            expected=(201,),
        )["test_cases"][0]["id"]
        job = queue(stored)
        run_worker(label, allow=True)
        artifact = outputs(job)
        result = artifact[1] if artifact else {}
        assessment = job_row(job)["assessment"] or {}
        items = {i["identity_id"]: i for i in assessment.get("identities", [])}
        evidence = req("GET", base + f"/evidence?job_id={job}&limit=200")["evidence"]
        scans = req("GET", base + f"/scans?job_id={job}")["scans"]
        record(
            label + " uploads bound evidence",
            job_row(job)["status"] == "done"
            and bool(artifact)
            and bool(evidence)
            and all(e["job_id"] == job and e["case_id"] == stored for e in evidence),
        )
        record(
            label + " retains triage candidates",
            len(scans) == len(result.get("findings", []))
            and all(s["status"] == "new" for s in scans),
        )
        record(
            label + " strips response and credential values",
            all(
                v not in json.dumps([result, evidence, assessment])
                for v in [
                    *tokens.values(),
                    "do-not-retain-session-value",
                    '"value": "initial"',
                    '"value": "changed"',
                ]
            ),
        )
        return result, assessment, items, evidence, state["requests"][mark:]

    for mode, decision in [
        ("vulnerable", "allowed"),
        ("fixed", "denied"),
        ("unknown", "inconclusive"),
    ]:
        spec = copy.deepcopy(common)
        spec.update(
            id="semantic-assertion-" + mode,
            request={"method": "GET", "url": target + "/semantic/record"},
        )
        for expected in spec["expected_access"]:
            expected["response_assertions"] = [
                {"json_pointer": "/access", "equals": "allowed", "decision": "allow"},
                {"json_pointer": "/error", "equals": "private", "decision": "deny"},
            ]
        result, assessment, items, evidence, traffic = execute(spec["id"], mode, spec)
        peer = items.get("peer", {})
        record(
            mode + " assertion separates raw HTTP from scanner conclusion",
            len(traffic) == 4
            and len(result.get("executions", [])) == 2
            and all(x["status_code"] == 200 for x in result.get("executions", []))
            and peer.get("observed_outcome") == "allow"
            and peer.get("reported_decision") == decision
            and peer.get("source") == "response_assertion"
            and peer.get("state")
            == ("inconclusive" if mode == "unknown" else "evaluated")
            and (
                peer.get("matched_assertions")
                == ([] if mode == "unknown" else [1 if mode == "fixed" else 0])
            ),
        )
        record(
            mode + " assertion survives evidence upload",
            any(
                "response_assertion" in e["body"] and decision in e["body"]
                for e in evidence
            ),
        )

    for mode, decision in [("vulnerable", "allowed"), ("fixed", "denied")]:
        spec = copy.deepcopy(common)
        spec.update(
            id="semantic-write-" + mode,
            mutating=True,
            request={"method": "PUT", "url": target + "/verification/write"},
            write_verification={
                "strategy": "changed",
                "environment": "synchronous_isolated",
                "identity": identity("reader", "LAB_ADMIN_TOKEN", "admin"),
                "request": {"method": "GET", "url": target + "/verification/state"},
                "json_pointer": "/value",
                "changed_to": "changed",
                "reset": {
                    "as": "owner",
                    "request": {"method": "PUT", "url": target + "/verification/reset"},
                },
            },
        )
        result, assessment, items, evidence, traffic = execute(spec["id"], mode, spec)
        peer, owner = items.get("peer", {}), items.get("owner", {})
        proof = peer.get("verification", {})
        record(
            mode + " write retains independent reader provenance",
            len(traffic) == 13
            and [x["identity"] for x in traffic[:3]] == ["owner", "peer", "admin"]
            and all(
                x["identity"] == "admin"
                for x in traffic
                if x["path"] == "/verification/state"
            )
            and all(
                x["identity"] == "owner"
                for x in traffic
                if x["path"] == "/verification/reset"
            )
            and proof.get("reader_identity_id") == "reader"
            and proof.get("reader_credential_status") == "preflight_passed"
            and proof.get("before_statuses") == [200, 200]
            and proof.get("after_status") == 200
            and proof.get("reset_status") == 204
            and proof.get("strategy") == "changed"
            and proof.get("environment") == "synchronous_isolated",
        )
        record(
            mode + " write uses effect rather than masked status",
            peer.get("reported_decision") == decision
            and peer.get("state") == "evaluated"
            and peer.get("source") == "write_verification"
            and owner.get("reported_decision") == "allowed"
            and owner.get("state") == "evaluated"
            and all(x["status_code"] == 204 for x in result.get("executions", []))
            and peer.get("write_verification")
            == ("verified_effect" if mode == "vulnerable" else "verified_no_effect"),
        )
        record(
            mode + " readback survives evidence upload",
            any(
                "write_verification" in e["body"] and "reader_identity_id" in e["body"]
                for e in evidence
            ),
        )

    record(
        "scanner uploads never create or promote confirmed findings",
        req("GET", base + "/findings")["findings"] == initial_findings,
    )
    results["semantic_evidence"] = {
        "supported": all(p["passed"] for p in probes),
        "probes": probes,
    }
