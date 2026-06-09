"use client";

import { useEffect, useRef, useState } from "react";
import type { ScanJobUI } from "../types";
import { useAppContext } from "../context/AppContext";
import { initJobs, nextId, computeYield, logFor, RUNNER } from "./jobs/mockData";
import Bridge from "./jobs/Bridge";
import Telemetry from "./jobs/Telemetry";
import Composer from "./jobs/Composer";
import JobBoard from "./jobs/JobBoard";
import Terminal from "./jobs/Terminal";

const ACCENT = "#f59e0b";
const LS = "vardrmap:jobs:prefs";

type Prefs = { view: "stream" | "pipeline" | "table"; collapsed: boolean; showTerminal: boolean };

function loadPrefs(): Prefs {
  if (typeof window === "undefined") return { view: "stream", collapsed: false, showTerminal: true };
  try {
    const stored = localStorage.getItem(LS);
    if (stored) return { view: "stream", collapsed: false, showTerminal: true, ...JSON.parse(stored) };
  } catch { /* ignore */ }
  return { view: "stream", collapsed: false, showTerminal: true };
}

type Toast = { text: string; id: number };

function ToastBanner({ msg, accent }: { msg: Toast | null; accent: string }) {
  if (!msg) return null;
  const err = /fail|offline|error/i.test(msg.text);
  return (
    <div className="mb-5 flex items-center gap-2.5 rounded-lg border px-4 py-3 text-sm"
      style={err
        ? { borderColor: "#7f1d1d", backgroundColor: "rgba(127,29,29,0.18)", color: "#fca5a5" }
        : { borderColor: `${accent}33`, backgroundColor: `${accent}0d`, color: accent }}>
      <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full"
        style={{ backgroundColor: err ? "#f87171" : accent }} />
      {msg.text}
    </div>
  );
}

export default function JobsSection({ programId, defaultTool, hideHeader }: { programId: string; defaultTool?: string; hideHeader?: boolean }) {
  void programId; // TODO: replace mock data with GET /programs/{id}/jobs + SSE stream

  const { selectedProgram } = useAppContext();
  const scopeCount  = selectedProgram?.scope.in.length  ?? 14;
  const reconCount  = selectedProgram?.recon_count      ?? 142;
  const programName = selectedProgram?.name             ?? "Active Program";

  // Persisted UI prefs
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  function pref<K extends keyof Prefs>(key: K, val: Prefs[K]) {
    setPrefs((p) => {
      const next = { ...p, [key]: val };
      try { localStorage.setItem(LS, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }

  const [jobs,          setJobs]          = useState<ScanJobUI[]>(initJobs);
  const [runnerOnline,  setRunnerOnline]  = useState(true);
  const [autoRun,       setAutoRun]       = useState(false);
  const [lastPoll,      setLastPoll]      = useState(() => new Date().toISOString());
  const [activeId,      setActiveId]      = useState<string | null>("job_095");
  const [pulseKey,      setPulseKey]      = useState(0);
  const [toast,         setToast]         = useState<Toast | null>(null);

  function flash(text: string) { setToast({ text, id: Date.now() }); }
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(id);
  }, [toast]);

  // refs so the interval closure reads fresh values without re-subscribing
  const onlineRef = useRef(runnerOnline);
  const autoRef   = useRef(autoRun);
  const runReqRef = useRef(false);
  const tickN     = useRef(0);

  useEffect(() => { onlineRef.current = runnerOnline; }, [runnerOnline]);
  useEffect(() => { autoRef.current   = autoRun; },     [autoRun]);

  // Simulation engine — advances running jobs, claims pending when allowed
  useEffect(() => {
    const iv = setInterval(() => {
      tickN.current++;
      const online = onlineRef.current;

      if (online && tickN.current % 3 === 0) {
        setLastPoll(new Date().toISOString());
        setPulseKey((k) => k + 1);
      }

      setJobs((prev) => {
        let next = prev.map((j) => ({ ...j }));
        const runningCount = () => next.filter((j) => j.status === "running").length;

        // advance running jobs
        next = next.map((j) => {
          if (j.status !== "running" || !online) return j;
          const inc = 6 + Math.random() * 10;
          const p = Math.min(100, Math.round(j.progress + inc));
          const full = j._full ?? [];
          const shown = Math.max(1, Math.floor((p / 100) * full.length));
          const log = full.slice(0, shown);
          if (p >= 100) {
            const dur = j.startedAt
              ? Date.now() - new Date(j.startedAt).getTime()
              : 90000;
            return { ...j, status: "done", progress: 100, log: full, endedAt: new Date().toISOString(), durationMs: dur };
          }
          return { ...j, progress: p, log };
        });

        // claim pending jobs when allowed and capacity available
        const allowClaim = online && (autoRef.current || runReqRef.current);
        if (allowClaim) {
          while (runningCount() < RUNNER.concurrency) {
            const pending = next
              .map((j, i) => ({ j, i }))
              .filter((x) => x.j.status === "pending")
              .sort((a, b) => new Date(a.j.queuedAt).getTime() - new Date(b.j.queuedAt).getTime());
            if (!pending[0]) { runReqRef.current = false; break; }
            const { j, i } = pending[0];
            const y = computeYield(j.tool, j.targets);
            const claimed: ScanJobUI = {
              ...j, yield: y, status: "running", progress: 4,
              startedAt: new Date().toISOString(),
            };
            claimed._full = logFor(claimed);
            claimed.log = claimed._full.slice(0, 1);
            next[i] = claimed;
          }
        }

        return next;
      });
    }, 800);
    return () => clearInterval(iv);
  }, []);

  const sorted       = [...jobs].sort((a, b) => new Date(b.queuedAt).getTime() - new Date(a.queuedAt).getTime());
  const activeJob    = jobs.find((j) => j.id === activeId) ?? null;
  const pendingCount = jobs.filter((j) => j.status === "pending").length;
  const runningCount = jobs.filter((j) => j.status === "running").length;
  const busy         = runningCount > 0;

  function queueJob(spec: { tool: string; source: string; config: Record<string, unknown>; targets: number; yieldKind: string }) {
    const job: ScanJobUI = {
      id: nextId(), tool: spec.tool, source: spec.source, config: spec.config,
      status: "pending", targets: spec.targets, progress: 0, yield: 0,
      yieldKind: spec.yieldKind, queuedAt: new Date().toISOString(),
      startedAt: null, endedAt: null, durationMs: null, log: [], _full: [],
    };
    setJobs((p) => [job, ...p]);
    setActiveId(job.id);
    flash(autoRef.current && onlineRef.current
      ? "Job queued — runner will claim it shortly."
      : "Job queued. Run `vardrrunner jobs run` to execute.");
  }

  function runPending() {
    if (!runnerOnline) { flash("Runner offline — connect VardrRunner first."); return; }
    runReqRef.current = true;
    flash(`Dispatching ${pendingCount} pending job${pendingCount > 1 ? "s" : ""} to ${RUNNER.host}…`);
  }

  function toggleRunner() {
    setRunnerOnline((v) => {
      const nv = !v;
      flash(nv ? `VardrRunner reconnected · ${RUNNER.user}@${RUNNER.host}` : "VardrRunner disconnected — queue will hold.");
      return nv;
    });
  }

  function retry(id: string) {
    setJobs((p) => p.map((j) => j.id === id
      ? { ...j, status: "pending", progress: 0, yield: 0, log: [], _full: [], error: undefined, startedAt: null, endedAt: null, durationMs: null, queuedAt: new Date().toISOString() }
      : j));
    flash("Job re-queued.");
  }

  function cancel(id: string) {
    setJobs((p) => p.map((j) => j.id === id
      ? { ...j, status: "failed", error: "cancelled by operator", log: [...j.log, { kind: "err" as const, text: "✗ cancelled by operator" }] }
      : j));
    flash("Job cancelled.");
  }

  return (
    <div className="space-y-5">
      {/* Section header — suppressed when embedded in RunSection */}
      {!hideHeader && (
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-[#2e2e2e] pb-5">
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="text-2xl font-bold tracking-tight text-[#f1f5f9]">Scan Jobs</h2>
              <span className="rounded border border-[#2e2e2e] px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-[#52525b]">
                orchestration
              </span>
            </div>
            <p className="mt-1.5 text-sm text-[#52525b]">
              Dispatch recon &amp; scan jobs to VardrRunner on your machine — results stream back into VardrMap.
            </p>
          </div>
          {/* View switch */}
          <div className="flex rounded-lg border border-[#2e2e2e] bg-[#1a1a1a] p-0.5">
            {(["stream", "pipeline", "table"] as const).map((v) => (
              <button key={v} onClick={() => pref("view", v)}
                className="rounded-md px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider transition"
                style={prefs.view === v ? { backgroundColor: "#2e2e2e", color: "#f1f5f9" } : { color: "#52525b" }}>
                {v}
              </button>
            ))}
          </div>
        </div>
      )}
      {/* View switch — shown standalone when embedded */}
      {hideHeader && (
        <div className="flex justify-end">
          <div className="flex rounded-lg border border-[#2e2e2e] bg-[#1a1a1a] p-0.5">
            {(["stream", "pipeline", "table"] as const).map((v) => (
              <button key={v} onClick={() => pref("view", v)}
                className="rounded-md px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider transition"
                style={prefs.view === v ? { backgroundColor: "#2e2e2e", color: "#f1f5f9" } : { color: "#52525b" }}>
                {v}
              </button>
            ))}
          </div>
        </div>
      )}

      <ToastBanner msg={toast} accent={ACCENT} />

      {/* Bridge */}
      <Bridge
        accent={ACCENT}
        runnerOnline={runnerOnline}
        autoRun={autoRun}
        lastPoll={lastPoll}
        queueDepth={pendingCount}
        runningCount={runningCount}
        busy={busy}
        pulseKey={pulseKey}
        collapsed={prefs.collapsed}
        onToggleRunner={toggleRunner}
        onToggleAuto={() => setAutoRun((v) => !v)}
        onToggleCollapse={() => pref("collapsed", !prefs.collapsed)}
      />

      {/* Telemetry */}
      <Telemetry jobs={jobs} accent={ACCENT} />

      {/* Composer + board + terminal */}
      <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
        <div>
          <Composer
            accent={ACCENT}
            onQueue={queueJob}
            runnerOnline={runnerOnline}
            scopeCount={scopeCount}
            reconCount={reconCount}
            programName={programName}
            initialTool={defaultTool}
          />
        </div>
        <div className="space-y-5">
          <JobBoard
            jobs={sorted}
            accent={ACCENT}
            view={prefs.view}
            activeId={activeId}
            onSelect={(id) => { setActiveId(id); pref("showTerminal", true); }}
            onRunPending={runPending}
            pendingCount={pendingCount}
            runnerOnline={runnerOnline}
            autoRun={autoRun}
          />

          {prefs.showTerminal ? (
            <Terminal
              job={activeJob}
              accent={ACCENT}
              onClose={() => pref("showTerminal", false)}
              onRetry={retry}
              onCancel={cancel}
            />
          ) : (
            <button
              onClick={() => pref("showTerminal", true)}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-[#2e2e2e] py-3 font-mono text-[11px] text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" />
              </svg>
              show terminal
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
