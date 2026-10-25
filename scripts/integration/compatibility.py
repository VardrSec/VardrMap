"""Run current sources and one older companion at a time; retain every result."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--gate", required=True, type=Path)
    parser.add_argument("--runner-python", required=True, type=Path)
    parser.add_argument(
        "--old-map", required=True, help="Exact local pre-semantic Map commit"
    )
    parser.add_argument(
        "--old-runner", required=True, help="Exact local pre-verifier Runner commit"
    )
    parser.add_argument(
        "--old-gate", required=True, help="Exact local pre-strategy Gate commit"
    )
    parser.add_argument("--go", default="go")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(
        tempfile.mkdtemp(prefix="vardr-compatibility-", dir=args.output)
    ).resolve()
    print(f"Matrix artifacts: {root}", flush=True)
    rows = []
    for name, flags in [
        ("current", []),
        ("old-map", ["--map-ref", args.old_map]),
        ("old-runner", ["--runner-ref", args.old_runner]),
        ("old-gate", ["--gate-ref", args.old_gate]),
    ]:
        command = [
            sys.executable,
            "-B",
            str(Path(__file__).with_name("run.py")),
            "--runner",
            str(args.runner.resolve()),
            "--gate",
            str(args.gate.resolve()),
            "--runner-python",
            str(args.runner_python.absolute()),
            "--go",
            args.go,
            "--semantic-evidence",
            "--output",
            str(root),
            *flags,
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", timeout=300
        )
        (root / (name + ".log")).write_text(
            completed.stdout + completed.stderr, encoding="utf-8"
        )
        path = next(
            (
                Path(line.removeprefix("Artifacts: "))
                for line in completed.stdout.splitlines()
                if line.startswith("Artifacts: ")
            ),
            root / "missing",
        )
        result_path = path / "acceptance-results.json"
        result = (
            json.loads(result_path.read_text(encoding="utf-8"))
            if result_path.exists()
            else {}
        )
        checks = result.get("checks", [])
        baseline = [c for c in checks if not c["name"].lower().startswith("semantic")]
        semantics = result.get("semantic_evidence", {})
        baseline_ok = len(baseline) == 104 and all(c["passed"] for c in baseline)
        # An arbitrary crash or legacy failure is never expected incompatibility.
        observed = bool(semantics) and not result.get("harness_error") and baseline_ok
        supported = semantics.get("supported", False)
        expected = (
            (observed and supported and completed.returncode == 0)
            if name == "current"
            else (observed and not supported and completed.returncode == 1)
        )
        rows.append(
            {
                "combination": name,
                "artifacts": str(path),
                "baseline_checks_pass": baseline_ok,
                "semantic_supported": supported,
                "expected_result": expected,
                "failed_probes": [
                    p["name"] for p in semantics.get("probes", []) if not p["passed"]
                ],
                "exit_code": completed.returncode,
                "harness_error": result.get("harness_error"),
            }
        )
        print(json.dumps(rows[-1]), flush=True)
    (root / "matrix.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0 if all(r["expected_result"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
