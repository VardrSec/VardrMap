"""Real CLI/API readiness checks; no schema stamping, target traffic or installs."""

import json
import os
import subprocess


def run_platform_checks(root, backend, runner_key, readiness, migrated, check):
    check(
        "Platform readiness v1 matches actual migration setup",
        readiness.get("schema_version") == 1
        and readiness.get("component") == "vardrmap-api"
        and readiness.get("status") == ("ready" if migrated else "not_ready")
        and readiness.get("checks")
        == {"database": "ok", "migrations": "current" if migrated else "not_current"},
    )
    env = {
        **os.environ,
        "VARDRMAP_URL": backend,
        "VARDRMAP_API_KEY": runner_key,
        "PATH": str(root) + os.pathsep + os.environ["PATH"],
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [
            os.environ["RUNNER_PYTHON"],
            "-B",
            str(root / "diagnostic_cli.py"),
            "doctor",
            "--platform",
            "--offline",
            "--json",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    # Never retain the credential even if an unexpected dependency prints it.
    output = (result.stdout + result.stderr).replace(runner_key, "[REDACTED]")
    (root / "platform-doctor.log").write_text(output, encoding="utf-8")
    report = json.loads(result.stdout)
    rows = {row["name"]: row for row in report.get("checks", [])}
    check(
        "Platform doctor exit reflects readiness",
        result.returncode == (0 if migrated else 1)
        and report.get("healthy") is migrated,
    )
    check(
        "Platform doctor checks database and migrations over HTTP",
        rows.get("platform database", {}).get("status") == "ok"
        and rows.get("platform migrations", {}).get("status")
        == ("ok" if migrated else "fail"),
    )
    check(
        "Offline doctor skips release discovery",
        "release discovery skipped" in rows.get("version", {}).get("detail", ""),
    )
    check(
        "Platform doctor output contains no API key",
        runner_key not in result.stdout + result.stderr,
    )
