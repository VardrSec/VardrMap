"""Local acceptance test: actual HTTP backend, actual runner worker, actual Gate binary."""

import copy
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

root = Path(sys.argv[1]).resolve()
postgres = os.getenv("INTEGRATION_POSTGRES") == "1"
if postgres:
    from sqlalchemy.engine import make_url
    database_url = os.environ["INTEGRATION_DATABASE_URL"]
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql" or not (parsed.database or "").startswith("vardrmap_test"):
        raise ValueError("Integration requires an empty disposable vardrmap_test* PostgreSQL database")
    os.environ["DATABASE_URL"] = database_url
else:
    os.environ["DATABASE_URL"] = "sqlite:///" + str(
        root / ("acceptance-" + str(time.time_ns()) + ".db")
    )
os.environ["ENV"] = "staging" if postgres else "test"
os.environ["BACKEND_JWT_SECRET"] = "local-acceptance-fixture-signing-key-32-characters"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.path.insert(0, str(root / "map/backend"))
if postgres:
    from db import engine
    from sqlalchemy import inspect
    if inspect(engine).get_table_names():
        raise ValueError("Integration PostgreSQL database must be empty")
    engine.dispose()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root / "map/backend", check=True, timeout=90,
    )
import jwt, httpx, uvicorn
from main import app
from db import SessionLocal
from models import ScanJob

results = {
    "checks": [],
    "observations": [],
    "scope": f"Loopback HTTP, isolated {'PostgreSQL' if postgres else 'SQLite'}, source snapshots; no browser or production deployment.",
}


def check(name, condition, detail=""):
    results["checks"].append(
        {"name": name, "passed": bool(condition), "detail": detail}
    )
    print(("PASS " if condition else "FAIL ") + name, flush=True)


def token(user):
    return jwt.encode(
        {
            "sub": user,
            "username": user,
            "email": user + "@example.test",
            "aud": "vardrmap-backend",
            "iss": "vardrmap-frontend",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        os.environ["BACKEND_JWT_SECRET"],
        algorithm="HS256",
    )


tokens = {x: "lab-" + x + "-fixture-token" for x in ["owner", "peer", "cross", "admin"]}
state = {"mode": "vulnerable", "requests": []}
SEMANTIC_EVIDENCE = os.getenv("INTEGRATION_SEMANTIC_EVIDENCE") == "1"
REQUEST_CEILING = 140 if SEMANTIC_EVIDENCE else 100


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        who = next(
            (
                k
                for k, v in tokens.items()
                if self.headers.get("Authorization") == "Bearer " + v
            ),
            "anonymous",
        )
        state["requests"].append(
            {"identity": who, "path": self.path, "client": self.client_address[0]}
        )
        path = urlsplit(self.path).path
        denied = (
            who == "anonymous"
            or (path.startswith("/admin") and who != "admin")
            or (not path.startswith("/admin") and who not in ("owner", "admin"))
        )
        if len(state["requests"]) > REQUEST_CEILING:
            status, body = 503, {"error": "fixture_request_ceiling"}
        elif path == "/session":
            if state["mode"] == "expired-owner" and who == "owner":
                status, body = 401, {"error": "expired_fixture_token"}
            elif state["mode"] == "session-redirect":
                status, body = 302, {"error": "login_required"}
            elif state["mode"] == "session-html":
                status, body = 200, "<html>Login, no authenticated principal</html>"
            else:
                principal = "wrong-principal" if state["mode"] == "session-mismatch" else who
                status, body = 200, {"user": {"id": principal}, "session_secret": "do-not-retain-session-value"}
        elif SEMANTIC_EVIDENCE and path == "/semantic/record":
            status, body = 200, {"access": "allowed"}
            if who == "peer" and state["mode"] == "fixed":
                body = {"error": "private"}
            elif who == "peer" and state["mode"] == "unknown":
                body = {"message": "unknown"}
        elif SEMANTIC_EVIDENCE and path == "/verification/state":
            status, body = (200, {"value": state.get("value", "initial")}) if who == "admin" else (403, {"error": "wrong_reader"})
        elif state["mode"] == "rate-limited":
            status, body = 429, {"error": "rate_limited"}
        elif state["mode"] == "login-redirect":
            status, body = 302, {"error": "login_required"}
        elif state["mode"] == "server-error":
            status, body = 503, {"error": "temporarily_unavailable"}
        elif state["mode"] == "expired-owner" and who == "owner":
            status, body = 401, {"error": "expired_fixture_token"}
        elif state["mode"] == "body-denial" and denied:
            status, body = 200, {"error": {"code": "access_denied"}}
        elif state["mode"] in ("fixed", "fixed-hidden", "expired-owner") and denied:
            code = 404 if state["mode"] == "fixed-hidden" else 403
            status, body = (401 if who == "anonymous" else code), {"error": "forbidden"}
        elif path == "/users":
            query = parse_qs(urlsplit(self.path).query)
            page = query.get("page", ["1"])[0]
            status, body = 200, {"data": [{"user_id": "42", "tenant_id": "tenant-a"}],
                                  "page": page, "next": "2" if page == "1" else None}
        else:
            status, body = (
                200,
                {
                    "user_id": "42",
                    "tenant_id": "tenant-a",
                    "display_name": "Fixture Owner",
                    "api_key": "lab-sensitive-response-value",
                    "role": "admin",
                },
            )
        self.reply(status, body)

    def do_PUT(self):
        who = next((k for k, v in tokens.items() if self.headers.get("Authorization") == "Bearer " + v), "anonymous")
        state["requests"].append({"identity": who, "path": self.path, "client": self.client_address[0]})
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if not SEMANTIC_EVIDENCE or len(state["requests"]) > REQUEST_CEILING:
            self.reply(503, {"error": "fixture_request_ceiling"})
        elif self.path == "/verification/reset" and who == "owner":
            state["value"] = "initial"
            self.reply(204, None)
        elif self.path == "/verification/write" and who in ("owner", "peer"):
            if who == "owner" or state["mode"] == "vulnerable":
                state["value"] = "changed"
            self.reply(204, None)  # Masked response; only the reader proves effect.
        else:
            self.reply(403, {"error": "forbidden"})

    def reply(self, status, body):
        data = b"" if status == 204 else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Set-Cookie", "session=lab-response-cookie; HttpOnly")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
threading.Thread(target=fixture.serve_forever, daemon=True).start()
target = f"http://127.0.0.1:{fixture.server_port}"
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
sock.close()
backend = f"http://127.0.0.1:{port}"
server = uvicorn.Server(
    uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error", access_log=False
    )
)
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
headers = {"Authorization": "Bearer " + token("lab_operator")}
other = {"Authorization": "Bearer " + token("lab_other")}


def req(method, path, payload=None, expected=(200,), auth=None):
    r = httpx.request(
        method, backend + path, json=payload, headers=auth or headers, timeout=10
    )
    if r.status_code not in expected:
        raise AssertionError(
            method + " " + path + " -> " + str(r.status_code) + " " + r.text[:350]
        )
    return r.json() if r.content else None


def job_row(jid):
    with SessionLocal() as db:
        j = db.query(ScanJob).filter_by(id=jid).one()
        return {
            "status": j.status,
            "error": j.error_message,
            "config": copy.deepcopy(j.config),
            "assessment": copy.deepcopy(j.assessment),
        }


# Origins the fixture cases contact. Runner 0.54 refuses a credential reference the operator
# has not approved for the engagement and every origin; the harness acts as the operator and
# passes these to worker.py, which approves the fixture's disposable LAB_*_TOKEN references.
approved_origins = [target]


def run_worker(label, allow=False):
    env = os.environ.copy()
    env.update(
        {
            "LAB_BACKEND": backend,
            "LAB_RUNNER_KEY": runner_key,
            "LAB_APPROVE_ENGAGEMENT": pid,
            "LAB_APPROVE_ORIGINS": json.dumps(approved_origins),
            "VARDRRUNNER_ALLOW_PRIVATE_TARGETS": "1" if allow else "0",
            "PYTHONIOENCODING": "utf-8",
            "PATH": str(root) + os.pathsep + env["PATH"],
        }
    )
    for k, v in tokens.items():
        env["LAB_" + k.upper() + "_TOKEN"] = v
    p = subprocess.run(
        [os.environ["RUNNER_PYTHON"], "-B", str(root / "worker.py")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    (root / (label + ".log")).write_text(p.stdout + p.stderr, encoding="utf-8")
    check(label + " worker exited normally", p.returncode == 0)
    if p.returncode:
        from redaction import redact_text
        print(redact_text(p.stderr[-4000:]), flush=True)
        raise RuntimeError(f"{label} worker failed; see its retained log")


def queue(caseid):
    return req(
        "POST",
        base + "/jobs",
        {
            "tool_type": "vardrgate_api_test",
            "target_source": "scope",
            "config": {"test_case_id": caseid, "timeout": 5},
        },
    )["id"]


def outputs(jid):
    with sqlite3.connect(root / "worker-state/journal.sqlite3") as con:
        row = con.execute(
            "SELECT run_dir FROM runs WHERE job_id=? ORDER BY started_at DESC LIMIT 1",
            (jid,),
        ).fetchone()
    if not row or not row[0]:
        return None
    path = Path(row[0]) / "vardrgate_result.json"
    return (
        (path.stat().st_mtime, json.loads(path.read_text()), path)
        if path.exists()
        else None
    )


try:
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "backend did not start"
    req("POST", "/auth/sync")
    client_id = req(
        "POST", "/clients", {"name": "Local Fixture Client"}, expected=(200, 201)
    )["id"]
    pid = req(
        "POST",
        "/engagements",
        {
            "name": "Local API acceptance",
            "engagement_type": "pentest",
            "client_id": client_id,
        },
    )["id"]
    base = "/engagements/" + pid
    now = datetime.now(timezone.utc)
    req(
        "POST",
        base + "/authorizations",
        {
            "authorized_by": "Local test owner",
            "reference": "Loopback fixture only",
            "permits": "Local fixture API testing",
            "window_start": (now - timedelta(hours=1)).isoformat(),
            "window_end": (now + timedelta(hours=1)).isoformat(),
        },
        expected=(201,),
    )
    req(
        "POST",
        base + "/scope/in",
        {"kind": "url", "value": target},
        expected=(200, 201),
    )
    runner_key = req(
        "POST", "/auth/apikeys", {"label": "Local acceptance runner", "scope": "runner"}
    )["token"]
    exchange = req(
        "POST",
        base + "/api/exchanges",
        {
            "method": "GET",
            "url": target + "/users/42/profile?view=full&include=roles",
            "source_tool": "repeater",
            "identity_label": "owner",
            "request_headers": "Authorization: Bearer " + tokens["owner"],
            "response_status": 200,
            "response_body": '{"api_key":"lab-sensitive-response-value"}',
        },
        expected=(201,),
    )
    eid = exchange["endpoint"]["id"]
    check(
        "Captured request credential redacted",
        tokens["owner"] not in json.dumps(exchange),
    )
    preview = req("POST", base + "/test-cases/preview", {"endpoint_ids": [eid]})
    check(
        "Draft expectations remain undecided",
        all(
            x["decision"] == "skip"
            for x in preview["drafts"][0]["spec"]["expected_access"]
        ),
    )
    identities = []
    for key in ["owner", "peer", "cross", "admin"]:
        identities.append(
            {
                "id": key,
                "role": "admin" if key == "admin" else "user",
                "tenant_id": "tenant-b" if key == "cross" else "tenant-a",
                "credential": {
                    "type": "bearer",
                    "value_env": "LAB_" + key.upper() + "_TOKEN",
                },
            }
        )
    identities.append(
        {
            "id": "anonymous",
            "credential": {"type": "static_header", "header": "", "value": ""},
        }
    )
    spec = {
        "id": "lab-profile-check",
        "identities": identities,
        "request": {
            "method": "GET",
            "url": target + "/users/42/profile?view=full&include=roles",
        },
        "expected_access": [
            {
                "identity_id": i["id"],
                "decision": "allow" if i["id"] in ["owner", "admin"] else "deny",
                "forbid_sensitive_data": i["id"] not in ["owner", "admin"],
            }
            for i in identities
        ],
        "resource": {
            "type": "user_profile",
            "object_id": "42",
            "owner_identity": "owner",
            "tenant_id": "tenant-a",
            "tenant_field": "tenant_id",
        },
        "deny_status": [401, 403, 404],
    }
    saved = req(
        "POST",
        base + "/test-cases/reviewed",
        {"reviewed": True, "cases": [{"name": "Profile ownership", "spec": spec}]},
        expected=(201,),
    )
    caseid = saved["test_cases"][0]["id"]
    check(
        "Saved case retains references, not credentials",
        all(v not in json.dumps(saved) for v in tokens.values()),
    )
    check(
        "Cross-user case access hidden",
        httpx.get(
            backend + base + "/test-cases", headers=other, timeout=5
        ).status_code
        == 404,
    )
    # First exercise the unmodified queued-job path.
    default_jid = queue(caseid)
    mark = len(state["requests"])
    run_worker("default-queued-job")
    default = job_row(default_jid)
    check(
        "Default queue does not contact blocked loopback",
        len(state["requests"]) == mark,
    )
    results["observations"].append(
        {
            "name": "Unmodified queued loopback job",
            "status": default["status"],
            "error": default["error"],
            "config": default["config"],
        }
    )
    check(
        "Queued handoff reaches Gate despite legacy program_id",
        outputs(default_jid) is not None
        and "malformed job" not in (default["error"] or ""),
        default["error"] or "",
    )
    blocked_jid = queue(caseid)
    mark = len(state["requests"])
    run_worker("blocked-loopback")
    blocked = job_row(blocked_jid)
    unknown = outputs(blocked_jid)
    results["observations"].append(
        {
            "name": "Private target setting absent",
            "job": blocked,
            "outcomes": unknown[1]["executions"] if unknown else [],
        }
    )
    check(
        "Loopback remains blocked without explicit opt-in",
        len(state["requests"]) == mark,
    )
    check(
        "Blocked executions are not marked successful jobs",
        blocked["status"] != "done",
        str(blocked),
    )
    # Explicit operator setting enables this loopback-only test engagement.
    jid = queue(caseid)
    run_worker("vulnerable-api", allow=True)
    check(
        "Vulnerable fixture job completed",
        job_row(jid)["status"] == "done",
        job_row(jid)["error"] or "",
    )
    check("Completed vulnerable scan has a complete reported assessment, not a clean verdict",
          job_row(jid)["assessment"]["status"] == "conclusive"
          and job_row(jid)["assessment"]["candidate_findings"] > 0)
    artifact = outputs(jid)
    assert artifact, "Gate did not produce a result"
    result = artifact[1]
    categories = {x["category"] for x in result["findings"]}
    check(
        "BOLA, cross-tenant and anonymous access detected",
        {"potential_bola", "cross_tenant_access", "missing_authentication"}.issubset(
            categories
        ),
        str(sorted(categories)),
    )
    check(
        "Five identities executed against real fixture",
        len(result["executions"]) == 5
        and all(x["status_code"] == 200 for x in result["executions"]),
    )
    check(
        "Multi-parameter URL reaches the target unchanged",
        all(parse_qs(urlsplit(x["path"]).query) == {"view": ["full"], "include": ["roles"]}
            for x in state["requests"]),
    )
    check(
        "Gate artifact contains no credential/body values",
        all(
            x not in json.dumps(result)
            for x in list(tokens.values())
            + ["lab-sensitive-response-value", "lab-response-cookie"]
        ),
    )
    events = req("GET", "/jobs/" + jid + "/events")["events"]
    check(
        "Runner target telemetry persists",
        any(x["kind"] == "target_stats" for x in events),
    )
    scans = req("GET", base + "/scans?job_id=" + jid)["scans"]
    check(
        "Uploaded findings are triage candidates",
        len(scans) == len(result["findings"])
        and all(x["status"] == "new" for x in scans),
    )
    evidence = req("GET", base + "/evidence")["evidence"]
    check(
        "Execution evidence stored with hashes",
        len(evidence) == 5
        and all(
            hashlib.sha256(x["body"].encode()).hexdigest() == x["content_hash"]
            for x in evidence
        ),
    )
    check(
        "Structural response evidence survives upload",
        any("response_profile" in x["body"] for x in evidence),
    )
    check("Execution evidence has structured job, case and identity provenance",
          all(x["job_id"] == jid and x["case_id"] == caseid and x["identity_id"] for x in evidence))
    filtered = req("GET", base + "/evidence?job_id=" + jid + "&identity_id=peer")
    check("Evidence filters select the exact execution without parsing titles",
          filtered["total"] == 1 and filtered["evidence"][0]["identity_id"] == "peer")
    catalog = req("GET", base + "/playbooks")
    guide = req("GET", base + "/playbooks/API-01")
    check("Shared playbook catalog retains version and manual testing guidance",
          catalog["total"] == 3 and guide["version"] == "1.0" and bool(guide["manual_remainder"]))
    replay = req("POST", "/jobs/" + jid + "/upload", result)
    check(
        "Repeated upload is idempotent",
        len(req("GET", base + "/evidence")["evidence"]) == len(evidence),
    )
    chosen = next(x for x in scans if x["type"] == "potential_bola")
    fid = req(
        "POST",
        base + "/findings",
        {
            "title": "Verified fixture ownership failure",
            "severity": chosen["severity"],
            "asset": target + "/users/42/profile",
            "status": "triaged",
            "summary": "A same-tenant non-owner received the owner profile.",
            "steps": "Execute reviewed ownership case.",
            "impact": "Unauthorized object access.",
            "remediation": "Enforce object ownership.",
        },
    )["id"]
    evidence_ids = [x["id"] for x in evidence if x["identity_id"] == "peer"]
    for eid in evidence_ids:
        linked = req("POST", base + "/evidence/" + eid + "/link", {"finding_id": fid})
        original = next(x for x in evidence if x["id"] == eid)
        check(
            "Evidence link preserves original record",
            linked == {**original, "finding_id": fid},
        )
    attach = httpx.post(
        backend + base + "/findings/" + fid + "/activity",
        headers=headers,
        json={
            "kind": "retest",
            "outcome": "still_open",
            "notes": "Direct link from job evidence.",
            "evidence_ids": evidence_ids,
        },
        timeout=5,
    )
    check(
        "Uploaded job evidence can link directly to finding history",
        attach.status_code == 201,
        "HTTP "
        + str(attach.status_code)
        + "; reviewed link must precede finding activity",
    )
    req(
        "POST",
        base + "/findings/" + fid + "/activity",
        {
            "kind": "retest",
            "outcome": "still_open",
            "notes": "Real local replay confirms non-owner access.",
            "evidence_ids": evidence_ids,
        },
        expected=(201,),
    )
    report = req(
        "POST",
        base + "/deliverables",
        {
            "title": "Local API assessment",
            "executive_summary": "Ownership failure verified against a controlled fixture.",
            "methodology": "Five-identity authorization replay; explicit local private-target opt-in.",
            "limitations": f"Isolated {'PostgreSQL' if postgres else 'SQLite'} and loopback; no browser or deployed services.",
            "finding_ids": [fid],
            "evidence_ids": evidence_ids,
        },
        expected=(201,),
    )
    check(
        "Report includes scope, authorization, finding and evidence",
        len(report["snapshot"]["findings"]) == 1
        and bool(report["snapshot"]["authorizations"])
        and bool(report["snapshot"]["evidence"]),
    )
    frozen = copy.deepcopy(report)
    state["mode"] = "fixed"
    fixed_jid = queue(caseid)
    run_worker("fixed-api", allow=True)
    fixed = outputs(fixed_jid)[1]
    check(
        "Clean Gate result uploads successfully",
        job_row(fixed_jid)["status"] == "done",
        str(job_row(fixed_jid)),
    )
    check(
        "Fixed fixture has zero authorization findings",
        not fixed["findings"],
        str(fixed["findings"]),
    )
    check("Clean wire findings is an array", fixed["findings"] == [])
    observed = {x["identity_id"]: x["status_code"] for x in fixed["executions"]}
    check(
        "Fixed fixture enforces intended access",
        observed
        == {"owner": 200, "peer": 403, "cross": 403, "admin": 200, "anonymous": 401},
        str(observed),
    )
    fixed_evidence = req("GET", base + "/evidence")["evidence"]
    new_ids = [
        x["id"]
        for x in fixed_evidence
        if x["id"] not in {y["id"] for y in evidence}
        and x["source"] == "vardrgate"
        and not x["finding_id"]
    ]
    for eid in new_ids:
        req("POST", base + "/evidence/" + eid + "/link", {"finding_id": fid})
    req(
        "POST",
        base + "/findings/" + fid + "/activity",
        {
            "kind": "remediation",
            "notes": "Enabled ownership and tenant checks in the local fixture.",
        },
        expected=(201,),
    )
    req(
        "POST",
        base + "/findings/" + fid + "/activity",
        {
            "kind": "retest",
            "outcome": "verified_fixed",
            "notes": "Five-identity replay now matches every expected decision.",
            "evidence_ids": new_ids,
        },
        expected=(201,),
    )
    path = base + "/deliverables/" + report["deliverable_id"] + "/revisions"
    check(
        "Original report content remains unchanged", req("GET", path + "/1") == frozen
    )
    revision = req(
        "POST",
        path,
        {
            "title": "Local API assessment retest",
            "base_revision": 1,
            "finding_ids": [fid],
            "evidence_ids": new_ids,
        },
        expected=(201,),
    )
    check(
        "New report revision contains verified retest",
        any(x["outcome"] == "verified_fixed" for x in revision["snapshot"]["activity"]),
    )
    halted_jid = queue(caseid)
    req("POST", base + "/stop-work", {"reason": "Acceptance halt test"})
    mark = len(state["requests"])
    run_worker("stop-work", allow=True)
    check(
        "Stop-work prevents execution and retains pending job",
        len(state["requests"]) == mark and job_row(halted_jid)["status"] == "pending",
    )
    req("DELETE", base + "/stop-work")
    run_worker("released-stop-work", allow=True)
    check("Release resumes execution of held job", len(state["requests"]) == mark + 5)
    # Transport failure must remain distinguishable from a genuinely clean assessment.
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()
    unavailable = copy.deepcopy(spec)
    unavailable["id"] = "lab-unreachable"
    unavailable["request"]["url"] = f"http://127.0.0.1:{dead_port}/users/42/profile"
    approved_origins.append(f"http://127.0.0.1:{dead_port}")
    stored = req(
        "POST",
        base + "/test-cases",
        {"name": "Unreachable fixture", "spec": unavailable},
        expected=(201,),
    )["id"]
    dead_jid = queue(stored)
    run_worker("unreachable-api", allow=True)
    dead_result = outputs(dead_jid)[1]
    check(
        "Unreachable API is not a successful clean job",
        job_row(dead_jid)["status"] != "done",
        str(job_row(dead_jid)),
    )
    results["observations"].append(
        {
            "name": "Unreachable API",
            "job": job_row(dead_jid),
            "findings": len(dead_result["findings"] or []),
            "outcomes": [x.get("observed_outcome") for x in dead_result["executions"]],
        }
    )
    admin_spec = copy.deepcopy(spec)
    admin_spec["id"] = "lab-admin-check"
    admin_spec["request"]["url"] = target + "/admin/settings"
    admin_spec["resource"] = {"required_role": "admin"}
    admin_spec["role_hierarchy"] = ["user", "admin"]
    for x in admin_spec["expected_access"]:
        x["decision"] = "allow" if x["identity_id"] == "admin" else "deny"
    state["mode"] = "vulnerable"
    adminid = req(
        "POST",
        base + "/test-cases",
        {"name": "Function authorization", "spec": admin_spec},
        expected=(201,),
    )["id"]
    adminjid = queue(adminid)
    run_worker("admin-function", allow=True)
    admin_result = outputs(adminjid)[1]
    check(
        "Privilege escalation detected",
        any(x["category"] == "privilege_escalation" for x in admin_result["findings"]),
    )
    def scenario(name, mode, case):
        state["mode"] = mode
        mark = len(state["requests"])
        stored = req("POST", base + "/test-cases/reviewed", {
            "reviewed": True, "cases": [{"name": name, "spec": case}],
        }, expected=(201,))["test_cases"][0]["id"]
        job = queue(stored)
        run_worker(name, allow=True)
        artifact = outputs(job)
        assert artifact, f"{name}: missing Gate result"
        result = artifact[1]
        check(name + " sends exactly one request per identity", len(state["requests"]) == mark + 5)
        check(name + " avoids false authorization findings", not result["findings"])
        return job, result

    hidden = copy.deepcopy(spec)
    hidden["id"] = "lab-hidden-denial"
    _, hidden_result = scenario("hidden-denial", "fixed-hidden", hidden)
    check("Declared 404 denials retain intended outcomes", {
        x["identity_id"]: x["observed_outcome"] for x in hidden_result["executions"]
    } == {"owner": "allow", "admin": "allow", "peer": "deny", "cross": "deny", "anonymous": "deny"})

    body_denial = copy.deepcopy(spec)
    body_denial["id"] = "lab-body-denial"
    body_denial["deny_when"] = {"json_field": {"path": "error.code", "equals": "access_denied"}}
    body_job, body_result = scenario("body-denial", "body-denial", body_denial)
    check("HTTP 200 denial is evaluated against the reviewed body convention",
          all(x["status_code"] == 200 for x in body_result["executions"])
          and job_row(body_job)["status"] == "done")

    fixed_admin = copy.deepcopy(admin_spec)
    fixed_admin["id"] = "lab-fixed-admin"
    fixed_admin_job, _ = scenario("fixed-admin", "fixed", fixed_admin)
    check("Fixed admin authorization completes without privilege findings", job_row(fixed_admin_job)["status"] == "done")

    for mode, outcome in [("server-error", "server_error"), ("rate-limited", "client_error"), ("login-redirect", "redirect")]:
        previous_evidence = {x["id"] for x in req("GET", base + "/evidence?limit=200")["evidence"]}
        case = copy.deepcopy(spec)
        case["id"] = "lab-" + mode
        job, result = scenario(mode, mode, case)
        check(mode + " retains ambiguous execution outcomes rather than allow/deny decisions",
              all(x["observed_outcome"] == outcome for x in result["executions"]))
        stored_evidence = [x for x in req("GET", base + "/evidence?limit=200")["evidence"]
                           if x["id"] not in previous_evidence]
        check(mode + " preserves inconclusive outcomes in uploaded evidence",
              len(stored_evidence) == 5
              and all(outcome in x["body"] for x in stored_evidence))
        a = job_row(job)["assessment"]
        check(mode + " completion remains an inconclusive assessment",
              job_row(job)["status"] == "done" and a["status"] == "inconclusive"
              and a["inconclusive"] == 5 and not a["baseline_valid"])
        results["observations"].append({"name": mode, "job": job_row(job),
            "outcomes": [x["observed_outcome"] for x in result["executions"]],
            "interpretation": "Job completion records execution, not a clean authorization assessment."})

    state["mode"] = "expired-owner"
    expired_case = copy.deepcopy(spec)
    expired_case["id"] = "lab-expired-target-session"
    stored = req("POST", base + "/test-cases/reviewed", {
        "reviewed": True, "cases": [{"name": "Expired target session", "spec": expired_case}],
    }, expected=(201,))["test_cases"][0]["id"]
    expired_job = queue(stored)
    run_worker("expired-target-session", allow=True)
    expired_result = outputs(expired_job)[1]
    check("Expired owner credential produces an explicit expected-access mismatch",
          any(x["category"] == "authorization_mismatch" and x["identity_id"] == "owner"
              for x in expired_result["findings"]))

    for page_number in ("1", "2"):
        collection = copy.deepcopy(spec)
        collection["id"] = "lab-page-" + page_number
        collection["request"]["url"] = target + "/users?page=" + page_number + "&limit=1"
        scenario("collection-page-" + page_number, "fixed", collection)
        check("Collection page " + page_number + " reaches the reviewed page without query corruption",
              all(parse_qs(urlsplit(x["path"]).query) == {"page": [page_number], "limit": ["1"]}
                  for x in state["requests"][-5:]))

    # A transport canary, not an injection detector: Gate tests authorization.
    # This proves a reviewed parameter value survives capture, storage and replay.
    canary = "' OR 1=1--"
    parameter_case = copy.deepcopy(spec)
    parameter_case["id"] = "lab-parameter-canary"
    parameter_case["request"]["url"] = target + "/users/42/profile?q=" + quote(canary) + "&page=2"
    scenario("parameter-canary", "fixed", parameter_case)
    check("Injection canary is transported literally; no injection coverage is claimed",
          all(parse_qs(urlsplit(x["path"]).query) == {"q": [canary], "page": ["2"]}
              for x in state["requests"][-5:]))
    # Preflight checks precede every authorization request and retain only safe
    # diagnostics. Failed session checks spend no authorization traffic.
    for mode in ("fixed", "expired-owner", "session-mismatch", "session-html", "session-redirect"):
        case = copy.deepcopy(spec)
        case["id"] = "lab-preflight-" + mode
        for identity in case["identities"]:
            if identity["id"] != "anonymous":
                identity["preflight"] = {"url": target + "/session", "expected_status": 200,
                                          "json_fields": {"user.id": identity["id"]}}
        state["mode"] = mode
        mark = len(state["requests"])
        stored = req("POST", base + "/test-cases/reviewed", {
            "reviewed": True, "cases": [{"name": case["id"], "spec": case}],
        }, expected=(201,))["test_cases"][0]["id"]
        job = queue(stored)
        run_worker(case["id"], allow=True)
        result = outputs(job)[1]
        requests = state["requests"][mark:]
        a = job_row(job)["assessment"]
        evidence = req("GET", base + f"/evidence?job_id={job}&limit=200")["evidence"]
        if mode == "fixed":
            check("Valid sessions are verified before authorization testing", len(requests) == 9
                  and all(x["path"] == "/session" for x in requests[:4])
                  and len(result["executions"]) == 5 and not result["findings"]
                  and job_row(job)["status"] == "done" and a["preflight"]["status"] == "passed"
                  and a["status"] == "conclusive")
        else:
            check(mode + " preflight stops authorization traffic and fails the job", len(requests) == 4
                  and all(x["path"] == "/session" for x in requests)
                  and result["executions"] == result["findings"] == []
                  and job_row(job)["status"] == "failed" and a["status"] == "inconclusive"
                  and a["preflight"]["status"] == "failed")
        check(mode + " preflight retains bound diagnostics without response values",
              len(evidence) == (9 if mode == "fixed" else 4)
              and all(e["job_id"] == job and e["case_id"] == stored for e in evidence)
              and "do-not-retain-session-value" not in json.dumps(evidence)
              and "do-not-retain-session-value" not in json.dumps(result))
    if SEMANTIC_EVIDENCE:
        from semantic import run_semantic
        run_semantic(check=check, req=req, base=base, queue=queue,
                     run_worker=run_worker, outputs=outputs, job_row=job_row,
                     state=state, target=target, results=results, tokens=tokens)
    if os.getenv("INTEGRATION_PLATFORM_READINESS") == "1":
        from platform_checks import run_platform_checks
        readiness = req("GET", "/ready", expected=(200 if postgres else 503,))
        request_mark = len(state["requests"])
        run_platform_checks(root, backend, runner_key, readiness, postgres, check)
        check("Platform diagnostics sends no target requests", len(state["requests"]) == request_mark)
    check("Fixture request ceiling respected", len(state["requests"]) <= REQUEST_CEILING)
    check(
        "Fixture received loopback requests only",
        all(x["client"] == "127.0.0.1" for x in state["requests"]),
    )
    results["request_count"] = len(state["requests"])
except Exception as exc:
    results["harness_error"] = str(exc)
    traceback.print_exc()
finally:
    server.should_exit = True
    thread.join(timeout=5)
    fixture.shutdown()
    fixture.server_close()
    results["passed"] = sum(x["passed"] for x in results["checks"])
    results["failed"] = sum(not x["passed"] for x in results["checks"])
    (root / "acceptance-results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "passed": results["passed"],
                "failed": results["failed"],
                "harness_error": results.get("harness_error"),
            }
        ),
        flush=True,
    )


sys.exit(1 if results["failed"] or results.get("harness_error") else 0)
