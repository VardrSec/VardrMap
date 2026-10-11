"""Local acceptance test: actual HTTP backend, actual runner worker, actual Gate binary."""

import copy, hashlib, json, os, socket, sqlite3, subprocess, sys, threading, time, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

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
import jwt, requests, uvicorn
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
        if state["mode"] == "server-error":
            status, body = 503, {"error": "temporarily_unavailable"}
        elif state["mode"] == "fixed" and (
            who == "anonymous"
            or (path.startswith("/admin") and who != "admin")
            or (not path.startswith("/admin") and who not in ("owner", "admin"))
        ):
            status, body = (401 if who == "anonymous" else 403), {"error": "forbidden"}
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
        data = json.dumps(body).encode()
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
    r = requests.request(
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
        }


def run_worker(label, allow=False):
    env = os.environ.copy()
    env.update(
        {
            "LAB_BACKEND": backend,
            "LAB_RUNNER_KEY": runner_key,
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
        requests.get(
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
    evidence_ids = [x["id"] for x in evidence if "peer" in x["title"]]
    for eid in evidence_ids:
        linked = req("POST", base + "/evidence/" + eid + "/link", {"finding_id": fid})
        original = next(x for x in evidence if x["id"] == eid)
        check(
            "Evidence link preserves original record",
            linked == {**original, "finding_id": fid},
        )
    attach = requests.post(
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
            "limitations": "SQLite and loopback; no browser or deployed services.",
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
