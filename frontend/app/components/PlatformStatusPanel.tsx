"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "../context/AppContext";
import type { Observation, Readiness } from "../lib/platformStatus";
import { observationFreshness, parseReadiness, parseRunnerStatus, runnerFreshness } from "../lib/platformStatus";
import type { RunnerStatus } from "../types";
import { Panel } from "./ui";

function seen(value: string) {
  return new Date(value).toLocaleString(undefined, {timeZoneName:"short"});
}

function Badge({ children, good = false, warning = false }: { children: React.ReactNode; good?: boolean; warning?: boolean }) {
  return <span className={`rounded border px-2 py-1 text-xs ${good ? "border-[#a6e3a1]/30 text-[#a6e3a1]" : warning ? "border-[#f59e0b]/30 text-[#f59e0b]" : "border-[#2e2e2e] text-muted"}`}>{children}</span>;
}

export default function PlatformStatusPanel() {
  const { authFetch, state } = useAppContext();
  const [backend, setBackend] = useState<Observation<Readiness> | null>(null);
  const [runners, setRunners] = useState<Observation<RunnerStatus> | null>(null);
  const [now, setNow] = useState(Date.now);
  const [loading, setLoading] = useState(false);
  const [refreshIndex, setRefreshIndex] = useState(0);

  useEffect(() => {
    let active = true;
    let busy = false;
    let request: AbortController | null = null;
    async function refresh() {
      if (busy) return;
      busy = true;
      setLoading(true);
      const controller = new AbortController();
      request = controller;
      const timeout = setTimeout(() => controller.abort(), 8000);
      async function read<T>(path: string, parse: (value: unknown, status: number) => T | null, save: (result: Observation<T>) => void) {
        let result: Observation<T>;
        try {
          const response = await authFetch(path, { cache: "no-store", signal: controller.signal });
          if (!response.ok && response.status !== 503) {
            result = { kind: "unreachable", receivedAt: Date.now() };
          } else {
            const value = await response.json().catch(() => null);
            const parsed = parse(value, response.status);
            result = parsed ? { kind: "received", value: parsed, receivedAt: Date.now() } : { kind: "unknown", receivedAt: Date.now() };
          }
        } catch {
          result = { kind: "unreachable", receivedAt: Date.now() };
        }
        if (active) save(result);
      }
      try {
        await Promise.all([
          read("/ready", parseReadiness, setBackend),
          read("/runner/status", (value, status) => status === 200 ? parseRunnerStatus(value) : null, setRunners),
        ]);
      } finally {
        clearTimeout(timeout);
        busy = false;
        if (active) { setNow(Date.now()); setLoading(false); }
      }
    }
    async function start() {
      setBackend(null);
      setRunners(null);
      await refresh();
    }
    void start();
    const poll = setInterval(() => { void refresh(); }, 30_000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { active = false; request?.abort(); clearInterval(poll); clearInterval(clock); };
  }, [authFetch, state.session, refreshIndex]);

  const ready = backend?.kind === "received" ? backend.value : null;
  const backendFreshness = ready && backend ? observationFreshness(ready.checked_at, backend.receivedAt, now) : null;
  const backendLabel = !backend ? "Checking" : backend.kind !== "received" ?
    (backend.kind === "unreachable" ? "Unreachable" : "Unknown") : backendFreshness !== "recent" ?
    (backendFreshness === "stale" ? "Stale" : "Unknown") : ready?.status === "ready" ? "Ready" : "Not ready";
  const report = runners?.kind === "received" ? runners.value : null;
  const reportFreshness = report && runners ? observationFreshness(report.checked_at!, runners.receivedAt, now) : null;
  const runnerLabel = !runners ? "Checking" : runners.kind !== "received" ?
    (runners.kind === "unreachable" ? "Unreachable" : "Unknown") : reportFreshness !== "recent" ?
    (reportFreshness === "stale" ? "Stale" : "Unknown") : !report?.runners?.length ? "Unknown" : "Reported";

  return (
    <Panel title="Platform and Runner status">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-xs text-muted">Observations refresh every 30 seconds. Refreshing status starts no scans.</p>
        <button className="rounded-md border border-[#2e2e2e] px-3 py-2 text-xs text-[#94a3b8] disabled:opacity-50" onClick={() => setRefreshIndex(index => index + 1)} disabled={loading}>Refresh status</button>
      </div>
      <div className="space-y-5" aria-live="polite">
        <section aria-label="Backend readiness" className="rounded-lg border border-[#2e2e2e] p-4">
          <div className="flex items-center justify-between"><h4 className="text-sm text-[#f1f5f9]">VardrMap backend</h4><Badge good={backendLabel === "Ready"} warning={["Not ready", "Unreachable", "Stale"].includes(backendLabel)}>{backendLabel}</Badge></div>
          {ready && <><p className="mt-3 text-xs text-muted">Observed {seen(ready.checked_at)}</p><p className="mt-1 text-xs text-muted">Database: {ready.checks.database === "ok" ? "connected" : "unavailable"} · Migrations: {ready.checks.migrations.replaceAll("_", " ")}</p></>}
          <p className="mt-2 text-xs text-muted">Checks API/database readiness and the migration marker. Other components and end-to-end execution are not established by this check.</p>
        </section>
        <section aria-label="Runner reports" className="rounded-lg border border-[#2e2e2e] p-4">
          <div className="flex items-center justify-between"><h4 className="text-sm text-[#f1f5f9]">VardrRunner</h4><Badge warning={["Unreachable", "Stale"].includes(runnerLabel)}>{runnerLabel}</Badge></div>
          {report && <p className="mt-3 text-xs text-muted">Status fetched {seen(report.checked_at!)}</p>}
          {report?.runners?.length === 0 && <p className="mt-2 text-xs text-muted">No Runner has reported for this account.</p>}
          {report?.runners?.map(row => {
            const freshness = reportFreshness === "recent" ? runnerFreshness(row, now, report.stale_after_seconds) : reportFreshness ?? "unknown";
            return <div key={row.hostname} className="mt-3 border-t border-[#2e2e2e] pt-3">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm text-[#f1f5f9]">{row.hostname || "Unnamed Runner"}</span><Badge good={freshness === "recent"} warning={freshness === "stale"}>{freshness === "recent" ? "Recent report" : freshness === "stale" ? "Stale report" : "Unknown"}</Badge></div>
              <p className="mt-2 text-xs text-muted">Last seen {seen(row.last_seen!)} · Reported version {row.version || "unknown"}{row.os ? ` · ${row.os}` : ""}</p>
              <ul className="mt-2 flex flex-wrap gap-3 text-xs text-muted" aria-label={`Reported tools on ${row.hostname || "unnamed Runner"}`}>
                {Object.entries(row.tools).map(([name, tool]) => <li key={name}>{name}: {tool.ok ? "available" : "unavailable"}{tool.version ? ` (${tool.version})` : ""}</li>)}
              </ul>
            </div>;
          })}
          <p className="mt-3 text-xs text-muted">A heartbeat records contact and reported tool availability. It does not prove a worker is running, every tool mode works, or a target is reachable. Reports become stale after five minutes; run Runner diagnostics explicitly when needed.</p>
        </section>
      </div>
    </Panel>
  );
}
