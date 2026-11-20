"""Opt-in checks for the coordinated semantic evidence rollout, using real workers."""

import copy
import json


def check_write_projections(*, record, req, base, target, jobs):
    """Read the paired fixture's stored job assessments, matrix and cited records."""
    exchange = req(
        "POST", base + "/api/exchanges",
        {"method": "PUT", "url": target + "/verification/write", "identity_label": "owner",
         "response_status": 204},
        expected=(201,),
    )
    endpoint_id = exchange["endpoint"]["id"]
    # Older Map snapshots in the compatibility matrix can lack these projections.
    coverage = req("GET", base + "/api/coverage", expected=(200, 404))
    matrix = req("GET", base + "/api/relationships", expected=(200, 404)).get("boundary_matrix", [])
    operation = next((op for op in coverage.get("operations", []) if op["endpoint_id"] == endpoint_id), {})
    job_details = {row["id"]: row for row in req("GET", base + "/jobs")["jobs"]}
    cases = {row["latest_job_id"]: row for row in operation.get("cases", [])}
    for mode, job in jobs.items():
        assessment = job_details[job]["assessment"] or {}
        case_id = job_details[job]["config"]["test_case_id"]
        case = cases.get(job, {})
        by_identity = {row["identity_id"]: row for row in assessment.get("identities", [])}
        rows = req("GET", base + f"/evidence?job_id={job}")["evidence"]
        executions = {}
        preflights = {}
        for row in rows:
            detail = json.loads(row["body"])
            records = preflights if detail.get("phase") == "identity_preflight" else executions
            records[row["identity_id"]] = row
        record(
            mode + " coverage retains the valid bound assessment",
            case.get("case_id") == case_id and assessment.get("case_id") == case_id
            and case.get("assessment_status") == assessment.get("status") == "conclusive"
            and case.get("baseline_valid") is True and assessment.get("baseline_valid") is True
            and assessment.get("case_snapshot_verified") is True,
        )
        for identity in ("owner", "peer"):
            allowed = identity == "owner" or mode == "vulnerable"
            expected = "allow" if identity == "owner" else "deny"
            decision = "allowed" if allowed else "denied"
            effect = "verified_effect" if allowed else "verified_no_effect"
            stored = by_identity.get(identity, {})
            result = case.get("identity_results", {}).get(identity, {})
            observations = [
                obs for cell in matrix if cell["endpoint_id"] == endpoint_id and cell["identity_id"] == identity
                for obs in cell["observations"] if obs["job_id"] == job and obs["case_id"] == case_id
            ]
            evidence = json.loads(executions.get(identity, {}).get("body", "{}"))
            job_result = {**stored, "expected": stored.get("expected_decision"), "observed": stored.get("observed_outcome")}
            fields = {"expected": expected, "observed": "allow", "reported_decision": decision,
                      "source": "write_verification", "write_verification": effect}
            record(
                f"{mode} {identity} job detail, coverage and matrix agree on the 204 write",
                evidence.get("status_code") == 204 and evidence.get("observed_outcome") == "allow"
                and job_result.get("state") == result.get("state") == "evaluated"
                and bool(observations) and all(obs.get("assessment_state") == "evaluated" for obs in observations)
                and all(fields.items() <= row.items() for row in [job_result, result, *observations]),
            )
        references = [ref for ref in operation.get("candidate_evidence", []) if ref["job_id"] == job]
        scans = req("GET", base + f"/scans?job_id={job}")["scans"]
        count = 1 if mode == "vulnerable" else 0
        record(
            mode + " job contributes the expected candidates and backing references",
            assessment.get("candidate_findings") == len(scans) == len(references) == count
            and all(scan["status"] == "new" for scan in scans)
            and operation.get("candidates") == {"open": 1, "promoted": 0, "false_positive": 0, "backing_evidence": 1},
        )
        if mode == "vulnerable":
            resource = executions.get("peer", {})
            preflight = preflights.get("peer", {})
            ref = references[0] if references else {}
            opened = req("GET", base + "/evidence/" + ref["evidence_id"], expected=(200, 404, 405)) if ref else {}
            record(
                "vulnerable peer resource record remains available after the fixed job",
                ref.get("identity_id") == "peer" and ref.get("case_id") == case_id
                and ref.get("expected") == "deny" and ref.get("observed") == "allow"
                and ref.get("reported_decision") == "allowed" and ref.get("source") == "write_verification"
                and ref.get("write_verification") == "verified_effect"
                and preflight.get("case_id") == resource.get("case_id") == case_id
                and preflight.get("created_at", "") > resource.get("created_at", "")
                and bool(ref.get("content_hash")) and ref["content_hash"] == resource.get("content_hash")
                and ref.get("evidence_id") == resource.get("id") and opened == resource,
            )


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
        return job, result, assessment, items, evidence, state["requests"][mark:]

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
        _, result, assessment, items, evidence, traffic = execute(spec["id"], mode, spec)
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

    write_jobs = {}
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
        job, result, assessment, items, evidence, traffic = execute(spec["id"], mode, spec)
        write_jobs[mode] = job
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

    check_write_projections(record=record, req=req, base=base, target=target, jobs=write_jobs)
    record(
        "scanner uploads never create or promote confirmed findings",
        req("GET", base + "/findings")["findings"] == initial_findings,
    )
    results["semantic_evidence"] = {
        "supported": all(p["passed"] for p in probes),
        "probes": probes,
    }
