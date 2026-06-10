"""
Safe subprocess runner. Only tools in ALLOWED_TOOLS can be executed.
Commands are built as argument lists — shell=True is never used.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator, Optional

# Allowlist maps subcommand names to their executable names.
# Add new tools here only — never allow arbitrary executables.
ALLOWED_TOOLS = {
    "httpx":     "httpx",
    "nuclei":    "nuclei",
    "subfinder": "subfinder",
}


def tool_available(name: str) -> bool:
    """Return True if the tool binary exists on PATH."""
    return shutil.which(ALLOWED_TOOLS.get(name, "")) is not None


def check_tool(name: str) -> None:
    """Raise SystemExit with a helpful message if the tool is not installed."""
    if not tool_available(name):
        import typer
        raise typer.BadParameter(
            f"'{name}' not found on PATH. Install it and make sure it is executable.",
            param_hint=name,
        )


def run_httpx(targets: list[str], output_path: Path) -> int:
    """Run httpx against a list of targets. Output is JSONL written to output_path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(targets))
        targets_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["httpx"],
        "-l", targets_file,
        "-json",
        "-o", str(output_path),
        "-silent",
    ]
    result = subprocess.run(cmd, check=False)
    Path(targets_file).unlink(missing_ok=True)
    return result.returncode


def run_nuclei(
    targets: list[str],
    output_path: Path,
    severity: Optional[str] = None,
    templates: Optional[str] = None,
) -> int:
    """Run nuclei against a list of targets. Output is JSONL written to output_path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(targets))
        targets_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["nuclei"],
        "-l", targets_file,
        "-json-export", str(output_path),
        "-silent",
    ]
    if severity:
        cmd += ["-severity", severity]
    if templates:
        cmd += ["-t", templates]

    result = subprocess.run(cmd, check=False)
    Path(targets_file).unlink(missing_ok=True)
    return result.returncode


def _run_streaming(cmd: list[str], targets_file: str) -> Iterator[tuple[str, str]]:
    """Execute cmd and yield (kind, text) log line pairs. Cleans up targets_file when done."""
    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ) as proc:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip()
                if line:
                    yield ("out", line)
            proc.wait()
            if proc.returncode != 0:
                yield ("warn", f"process exited with code {proc.returncode}")
    finally:
        Path(targets_file).unlink(missing_ok=True)


def run_httpx_streaming(targets: list[str], output_path: Path) -> Iterator[tuple[str, str]]:
    """Run httpx, yielding (kind, text) log lines as they're produced."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(targets))
        targets_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["httpx"],
        "-l", targets_file,
        "-json",
        "-o", str(output_path),
    ]
    yield from _run_streaming(cmd, targets_file)


def run_nuclei_streaming(
    targets: list[str],
    output_path: Path,
    severity: Optional[str] = None,
    templates: Optional[str] = None,
) -> Iterator[tuple[str, str]]:
    """Run nuclei, yielding (kind, text) log lines as they're produced."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(targets))
        targets_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["nuclei"],
        "-l", targets_file,
        "-json-export", str(output_path),
    ]
    if severity:
        cmd += ["-severity", severity]
    if templates:
        cmd += ["-t", templates]

    yield from _run_streaming(cmd, targets_file)


def run_subfinder_streaming(domains: list[str], output_path: Path) -> Iterator[tuple[str, str]]:
    """Run subfinder, yielding (kind, text) log lines as they're produced."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(domains))
        domains_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["subfinder"],
        "-dL", domains_file,
        "-o",  str(output_path),
    ]
    yield from _run_streaming(cmd, domains_file)


def run_subfinder(domains: list[str], output_path: Path) -> int:
    """Run subfinder against a list of root domains. Output is one host per line."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(domains))
        domains_file = tmp.name

    cmd = [
        ALLOWED_TOOLS["subfinder"],
        "-dL", domains_file,
        "-o",  str(output_path),
        "-silent",
    ]
    result = subprocess.run(cmd, check=False)
    Path(domains_file).unlink(missing_ok=True)
    return result.returncode
