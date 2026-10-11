"""Snapshot three checkouts and run the loopback API engagement acceptance test."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def snapshot(source: Path, destination: Path) -> dict:
    """Include local edits/new source, excluding Git-ignored secrets and outputs."""
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=source,
        )
        .decode()
        .split("\0")
    )
    hashes = {}
    for relative in sorted(set(paths)):
        if not relative:
            continue
        path = source / relative
        if not path.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        hashes[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source)
        .decode()
        .strip(),
        "files": hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--gate", required=True, type=Path)
    parser.add_argument("--runner-python", required=True, type=Path)
    parser.add_argument("--go", default="go")
    parser.add_argument(
        "--output", type=Path, help="Parent for a fresh isolated run directory"
    )
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    root = Path(tempfile.mkdtemp(prefix="vardr-integration-", dir=args.output))
    print(f"Artifacts: {root}", flush=True)
    manifest = {}
    for name, source in [
        ("map", scripts.parents[1]),
        ("runner", args.runner),
        ("gate", args.gate),
    ]:
        manifest[name] = snapshot(source.resolve(), root / name)
    (root / "sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name in ("acceptance.py", "worker.py"):
        shutil.copy2(scripts / name, root / name)
    binary = root / ("vardrgate.exe" if os.name == "nt" else "vardrgate")
    subprocess.run(
        [args.go, "build", "-o", str(binary), "./cmd/vardrgate"],
        cwd=root / "gate",
        check=True,
    )
    env = {
        **os.environ,
        "RUNNER_PYTHON": str(args.runner_python.resolve()),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-B", str(root / "acceptance.py"), str(root)],
        cwd=root,
        env=env,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
