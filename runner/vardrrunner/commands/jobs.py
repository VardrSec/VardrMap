"""
Job queue commands: list pending jobs and run them locally.

The UI creates job records; VardrRunner polls /jobs/pending, executes
the tool locally, streams log lines back via POST /jobs/{id}/logs,
and uploads results via the existing import endpoint.
"""
import json as _json
import time
from pathlib import Path
from typing import Iterator, Optional

import typer
from rich.console import Console
from rich.table import Table

from vardrrunner import api, config, runner
from vardrrunner.commands.run import _confirm, _is_wildcard, _make_run_dir, _resolve_targets

console = Console()

_FLUSH_INTERVAL = 2.0   # seconds between log batch flushes to the API


def _post_sys(client: api.VardrMapClient, job_id: str, text: str) -> None:
    """Post a single system-level log line. Swallows errors — logs are best-effort."""
    try:
        client.post_logs(job_id, [{"kind": "sys", "text": text}])
    except Exception:
        pass


def _stream_and_log(
    client: api.VardrMapClient,
    job_id: str,
    line_iter: Iterator[tuple[str, str]],
) -> None:
    """Drain a log-line iterator, flushing batches to the API every 2 seconds."""
    batch: list[dict] = []
    last_flush = time.time()

    for kind, text in line_iter:
        batch.append({"kind": kind, "text": text})
        now = time.time()
        if now - last_flush >= _FLUSH_INTERVAL and batch:
            try:
                client.post_logs(job_id, batch)
            except Exception:
                pass
            batch = []
            last_flush = now

    if batch:
        try:
            client.post_logs(job_id, batch)
        except Exception:
            pass


def _wildcard_domains(scope: dict) -> list[str]:
    """Extract root domains from wildcard scope entries like *.example.com → example.com."""
    domains = []
    for item in scope.get("in", []):
        val = item.get("value", "")
        if _is_wildcard(val):
            stripped = val.lstrip("*").lstrip(".")
            if stripped:
                domains.append(stripped)
    return domains


def list_jobs() -> None:
    """Show all pending scan jobs for the authenticated user."""
    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)
    jobs = client.pending_jobs()

    if not jobs:
        console.print("[dim]No pending jobs.[/dim]")
        raise typer.Exit(0)

    table = Table(title="Pending Scan Jobs")
    table.add_column("ID",            style="dim", no_wrap=True)
    table.add_column("Tool",          style="bold")
    table.add_column("Source")
    table.add_column("Config",        style="dim")
    table.add_column("Created")

    for j in jobs:
        cfg_str = "  ".join(f"{k}={v}" for k, v in (j.get("config") or {}).items())
        table.add_row(
            j["id"][:8] + "…",
            j["tool_type"],
            j["target_source"],
            cfg_str or "—",
            j.get("created_at", "")[:16],
        )

    console.print(table)


def run_jobs(yes: bool = False) -> None:
    """Claim and execute all pending jobs for the authenticated user."""
    url, key = config.require_auth()
    client = api.VardrMapClient(url, key)
    jobs = client.pending_jobs()

    if not jobs:
        console.print("[dim]No pending jobs.[/dim]")
        raise typer.Exit(0)

    console.print(f"Found [bold]{len(jobs)}[/bold] pending job(s).")

    for job in jobs:
        job_id      = job["id"]
        tool_type   = job["tool_type"]
        target_src  = job["target_source"]
        program_id  = job["program_id"]
        cfg         = job.get("config") or {}

        console.rule(f"Job {job_id[:8]}… — {tool_type} / {target_src}")

        if not runner.tool_available(tool_type):
            console.print(f"[red]'{tool_type}' not found on PATH — marking job failed.[/red]")
            client.complete_job(job_id, "failed", error=f"'{tool_type}' not found on PATH")
            continue

        # Resolve targets
        try:
            if tool_type == "subfinder":
                scope_data = client.scope(program_id)
                targets = _wildcard_domains(scope_data)
                if not targets:
                    console.print("[yellow]No wildcard scope entries — marking job done.[/yellow]")
                    client.complete_job(job_id, "done")
                    continue
            else:
                status_code: Optional[int] = cfg.get("status_code")
                limit: int = int(cfg.get("limit", 100))
                targets = _resolve_targets(
                    client=client,
                    program_id=program_id,
                    scope=(target_src == "scope"),
                    from_recon=(target_src == "recon"),
                    target=None,
                    targets_file=None,
                    status_code=status_code,
                    limit=limit,
                )
        except SystemExit:
            client.complete_job(job_id, "failed", error="Failed to resolve targets")
            continue

        if not targets:
            console.print("[yellow]No targets resolved — marking job as done.[/yellow]")
            client.complete_job(job_id, "done")
            continue

        _confirm(targets, tool_type, yes)

        try:
            client.claim_job(job_id)
        except Exception as e:
            console.print(f"[red]Could not claim job:[/red] {e}")
            continue

        _post_sys(client, job_id, f"Starting {tool_type} on {len(targets)} target(s)…")

        run_dir = _make_run_dir()
        error_msg = ""
        try:
            if tool_type == "httpx":
                output = run_dir / "httpx.jsonl"
                console.print(f"Running httpx… output → [dim]{output}[/dim]")
                _stream_and_log(client, job_id, runner.run_httpx_streaming(targets, output))

            elif tool_type == "nuclei":
                output = run_dir / "nuclei.jsonl"
                severity  = cfg.get("severity")
                templates = ",".join(cfg["templates"]) if cfg.get("templates") else None
                label = f"severity={severity}" if severity else "all"
                console.print(f"Running nuclei ({label})… output → [dim]{output}[/dim]")
                _stream_and_log(
                    client, job_id,
                    runner.run_nuclei_streaming(targets, output, severity=severity, templates=templates),
                )

            else:  # subfinder
                output = run_dir / "subfinder.txt"
                console.print(f"Running subfinder… output → [dim]{output}[/dim]")
                _stream_and_log(client, job_id, runner.run_subfinder_streaming(targets, output))

            if not output.exists() or output.stat().st_size == 0:
                console.print("[yellow]No output produced — nothing to import.[/yellow]")
                _post_sys(client, job_id, "No output produced.")
                client.complete_job(job_id, "done")
                continue

            # For subfinder, convert to httpx-compatible JSONL before importing
            import_path = output
            if tool_type == "subfinder":
                hosts = [line.strip() for line in output.read_text().splitlines() if line.strip()]
                _post_sys(client, job_id, f"Discovered {len(hosts)} subdomain(s). Uploading…")
                jsonl_path = run_dir / "subfinder_httpx.jsonl"
                with jsonl_path.open("w") as fh:
                    for host in hosts:
                        fh.write(_json.dumps({"host": host, "source": "subfinder"}) + "\n")
                import_path = jsonl_path

            _post_sys(client, job_id, "Uploading results…")
            console.print("Uploading results…")
            result = client.import_file(program_id, tool_type if tool_type != "subfinder" else "httpx", str(import_path))
            count  = result.get("import_record", {}).get("imported_count", "?")
            _post_sys(client, job_id, f"Done. Imported {count} result(s).")
            console.print(f"[green]Done.[/green] Imported {count} result(s).")
            client.complete_job(job_id, "done")

        except Exception as e:
            error_msg = str(e)
            console.print(f"[red]Job failed:[/red] {error_msg}")
            _post_sys(client, job_id, f"Job failed: {error_msg[:200]}")
            client.complete_job(job_id, "failed", error=error_msg[:500])
