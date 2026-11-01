"""Naabu results through a real Runner worker into a real Map backend.

Checks source attribution, job linkage and re-observation of an existing row. The `naabu`
process itself is a deterministic stand-in that writes naabu's `-json` line format (the real
binary is exercised separately by the VardrSec tool/network acceptance against a loopback
fixture); everything after it, Runner's target resolution, argument construction, parsing,
upload and Map's storage, is real.
"""

import json
import os
import stat
import sys
from pathlib import Path

SHIM = '''"""Stand-in for naabu: the same -list/-top-ports/-json/-o/-silent contract and output."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

args = sys.argv[1:]


def value(flag):
    return args[args.index(flag) + 1]


hosts = [h for h in Path(value("-list")).read_text().split() if h]
config = json.loads(Path(__file__).with_name("naabu_config.json").read_text())
Path(config["record"]).write_text(json.dumps({"args": args, "hosts": hosts}))
if any("nmap" in a.lower() for a in args):
    sys.exit(2)
with open(value("-o"), "w") as output:
    for host in hosts:
        for port in config["ports"]:
            output.write(json.dumps({
                "ip": host, "port": port, "protocol": "tcp", "tls": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }) + "\\n")
'''


def install_shim(root: Path, record: Path, ports: list[int]) -> Path:
    """Put a `naabu` on the worker's PATH; returns the path the worker should execute.

    Runner passes tools an allowlisted environment (ADR 0022), so the stand-in is configured
    through a file next to it rather than through environment variables."""
    script = root / "naabu_shim.py"
    script.write_text(SHIM, encoding="utf-8")
    script.with_name("naabu_config.json").write_text(
        json.dumps({"record": str(record), "ports": ports}), encoding="utf-8"
    )
    if os.name == "nt":
        launcher = root / "naabu.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = root / "naabu"
        launcher.write_text(f"#!{sys.executable}\n" + SHIM, encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    return launcher


def run_naabu(*, check, req, base, run_worker, job_row, root, target, backend_port, results):
    record = root / "naabu-record.json"
    fixture_port = int(target.rsplit(":", 1)[1])
    ports = [fixture_port, backend_port]
    launcher = install_shim(root, record, ports)
    os.environ["LAB_NAABU_SHIM"] = str(launcher)
    services = base + "/services"
    # A row an earlier Nmap-era scan left behind: the legacy default label applies because
    # no source is sent.
    req(
        "POST",
        services,
        {"services": [{"host": "127.0.0.1", "port": fixture_port, "service_name": "http"}]},
        expected=(200, 201),
    )
    legacy = {s["port"]: s for s in req("GET", services)["services"]}
    check("Naabu: a row posted without a source keeps the legacy nmap label",
          legacy[fixture_port]["source"] == "nmap")

    job = req(
        "POST",
        base + "/jobs",
        {"tool_type": "naabu", "target_source": "scope", "config": {"top_ports": 100}},
    )["id"]
    run_worker("naabu", allow=True)
    check("Naabu: the job completes", job_row(job)["status"] == "done", str(job_row(job)))

    rows = req("GET", services + f"?job_id={job}")["services"]
    everything = req("GET", services)["services"]
    check("Naabu: both reported ports are linked to the job",
          sorted(s["port"] for s in rows) == sorted(ports))
    check("Naabu: every service the job produced is attributed to naabu",
          rows and all(s["source"] == "naabu" for s in rows), json.dumps(rows))
    check("Naabu: the job does not mislabel anything as nmap",
          not any(s["source"] == "nmap" for s in rows))
    check("Naabu: re-seeing a legacy row relabels it without duplicating",
          len([s for s in everything if s["port"] == fixture_port]) == 1
          and {s["port"] for s in everything} == set(ports))

    # Recorded, not asserted: existing upsert behavior replaces an earlier scan's service name
    # with the new scan's (empty for naabu).
    results["naabu_reobserved_service_name"] = {
        "before": "http",
        "after": next(s["service_name"] for s in everything if s["port"] == fixture_port),
    }
    seen = json.loads(record.read_text(encoding="utf-8"))
    args = seen["args"]
    check("Naabu: Runner resolves the scope URL to a bare host", seen["hosts"] == ["127.0.0.1"])
    check("Naabu: Runner runs it with JSON output, the top-port list and no Nmap hook",
          {"-list", "-top-ports", "-json", "-o", "-silent"} <= set(args)
          and not any("nmap" in a.lower() or a in ("-sV", "-sc") for a in args), str(args))
