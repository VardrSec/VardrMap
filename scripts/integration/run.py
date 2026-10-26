"""Snapshot three checkouts and run the loopback API engagement acceptance test."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


def snapshot(source: Path, destination: Path, ref: str | None = None) -> dict:
    """Include local edits/new source, excluding Git-ignored secrets and outputs."""
    if ref:
        revision = subprocess.check_output(
            ["git", "rev-parse", "--verify", ref + "^{commit}"], cwd=source,
        ).decode().strip()
        hashes = {}
        with tempfile.TemporaryFile() as archive:
            subprocess.run(["git", "archive", revision], cwd=source, stdout=archive, check=True)
            archive.seek(0)
            with tarfile.open(fileobj=archive) as contents:
                for member in contents:
                    relative = Path(member.name)
                    if relative.is_absolute() or relative.drive or ".." in relative.parts or member.issym() or member.islnk():
                        raise ValueError("Unsupported archive path or link")
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError("Unsupported archive entry")
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = contents.extractfile(member)
                    assert stream is not None
                    with stream, target.open("wb") as output:
                        shutil.copyfileobj(stream, output)
                    hashes[member.name] = hashlib.sha256(target.read_bytes()).hexdigest()
        return {"head": revision, "ref": ref, "files": hashes}
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
    parser.add_argument("--map-ref", help="Snapshot this local Map commit instead of working files")
    parser.add_argument("--runner-ref", help="Snapshot this local Runner commit instead of working files")
    parser.add_argument("--gate-ref", help="Snapshot this local Gate commit instead of working files")
    parser.add_argument("--semantic-evidence", action="store_true",
                        help="Require assertion and independent write-readback metadata end to end")
    parser.add_argument("--platform-readiness", action="store_true",
                        help="Check real Runner doctor against Map readiness without running jobs")
    parser.add_argument(
        "--postgres", action="store_true",
        help="Use INTEGRATION_DATABASE_URL (an empty disposable vardrmap_test* database)",
    )
    parser.add_argument(
        "--output", type=Path, help="Parent for a fresh isolated run directory"
    )
    args = parser.parse_args()
    if args.postgres and not os.getenv("INTEGRATION_DATABASE_URL"):
        parser.error("--postgres requires INTEGRATION_DATABASE_URL")
    scripts = Path(__file__).resolve().parent
    root = Path(tempfile.mkdtemp(prefix="vardr-integration-", dir=args.output))
    print(f"Artifacts: {root}", flush=True)
    manifest = {}
    for name, source, ref in [
        ("map", scripts.parents[1], args.map_ref),
        ("runner", args.runner, args.runner_ref),
        ("gate", args.gate, args.gate_ref),
    ]:
        manifest[name] = snapshot(source.resolve(), root / name, ref)
    (root / "sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name in ("acceptance.py", "worker.py", "semantic.py", "diagnostic_cli.py", "platform_checks.py"):
        shutil.copy2(scripts / name, root / name)
    binary = root / ("vardrgate.exe" if os.name == "nt" else "vardrgate")
    subprocess.run(
        [args.go, "build", "-o", str(binary), "./cmd/vardrgate"],
        cwd=root / "gate",
        check=True,
    )
    env = {
        **os.environ,
        # Unix venv interpreters are symlinks. Resolving that symlink invokes
        # the base interpreter and loses the venv's installed dependencies.
        "RUNNER_PYTHON": os.path.abspath(args.runner_python),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "INTEGRATION_POSTGRES": "1" if args.postgres else "0",
        "INTEGRATION_SEMANTIC_EVIDENCE": "1" if args.semantic_evidence else "0",
        "INTEGRATION_PLATFORM_READINESS": "1" if args.platform_readiness else "0",
    }
    return subprocess.run(
        [sys.executable, "-B", str(root / "acceptance.py"), str(root)],
        cwd=root,
        env=env,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
