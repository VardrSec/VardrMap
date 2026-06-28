"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RunnerStatus, ScanJob, ScanJobUI, ScheduledScan } from "../types";
import { useAppContext } from "../context/AppContext";
import { TOOLS } from "./jobs/mockData";
import Bridge from "./jobs/Bridge";
import Telemetry from "./jobs/Telemetry";
import Composer from "./jobs/Composer";
import JobBoard from "./jobs/JobBoard";
import SchedulesPanel from "./jobs/SchedulesPanel";
import Terminal from "./jobs/Terminal";

const ACCENT = "#f59e0b";
const LS = "vardrmap:jobs:prefs";
const POLL_ACTIVE_MS = 5000;
const POLL_IDLE_MS   = 30000;

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

function mapToUI(job: ScanJob): ScanJobUI {
  const started    = job.started_at   ? new Date(job.started_at).getTime()   : null;
  const ended      = job.completed_at ? new Date(job.completed_at).getTime() : null;
  const durationMs = started && ended ? ended - started : null;
  const progress   = job.status === "done" ? 100 : job.status === "running" ? 50 : 0;
  const toolDef    = TOOLS[job.tool_type];
  return {
    id:        job.id,
    tool:      job.tool_type,
    source:    job.target_source,
    config:    job.config,
    status:    job.status as ScanJobUI["status"],
    targets:   0,
    progress,
    yield:     0,
    yieldKind: toolDef?.yields ?? job.tool_type,
    queuedAt:  job.created_at   ?? new Date().toISOString(),
    startedAt: job.started_at,
    endedAt:   job.completed_at,
    durationMs,
    error:     job.error_message || undefined,
    log:       job.error_message ? [{ kind: "err" as const, text: job.error_message }] : [],
    _full:     [],
  };
}

export default function JobsSection({
  programId, defaultTool, prefillEpoch, hideHeader,
}: { programId: string; defaultTool?: string; prefillEpoch?: number; hideHeader?: boolean }) {
  const { authFetch, selectedProgram, navigate } = useAppContext();
  const scopeCount  = selectedProgram?.scope.in.length ?? 0;
  const programName = selectedProgram?.name            ?? "Active Program";

  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  function pref<K extends keyof Prefs>(key: K, val: Prefs[K]) {
    setPrefs((p) => {
      const next = { ...p, [key]: val };
      try { localStorage.setItem(LS, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }

  const [jobs,          setJobs]          = useState<ScanJobUI[]>([]);
  const [schedules,     setSchedules]     = useState<ScheduledScan[]>([]);
  const [loading,       setLoading]       = useState(true);
  const [runnerStatus,  setRunnerStatus]  = useState<RunnerStatus | null>(null);
  const [autoRun,       setAutoRun]       = useState(false);
  const [lastPoll,      setLastPoll]      = useState(() => new Date().toISOString());
  const [activeId,      setActiveId]      = useState<string | null>(null);
  const [pulseKey,      setPulseKey]      = useState(0);
  const [toast,         setToast]         = useState<Toast | null>(null);
  const [liveRecon,     setLiveRecon]     = useState<number | null>(null);

  const runnerOnline = runnerStatus?.online ?? false;
  // Live recon count for the Composer's queue card — refreshed every poll so it
  // reflects assets the runner just imported, not a stale program snapshot.
  const reconCount = liveRecon ?? selectedProgram?.recon_count ?? 0;
  useEffect(() => { setLiveRecon(null); }, [programId]);

  function flash(text: string) { setToast({ text, id: Date.now() }); }
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(id);
  }, [toast]);

  const jobsRef = useRef<ScanJobUI[]>([]);
  useEffect(() => { jobsRef.current = jobs; }, [jobs]);

  const loadJobs = useCallback(async () => {
    try {
      const [jobsRes, statusRes, reconRes] = await Promise.all([
        authFetch(`/programs/${programId}/jobs`),
        authFetch(`/runner/status`),
        authFetch(`/programs/${programId}/recon?limit=1`),
      ]);
      if (jobsRes.ok) {
        const data = await jobsRes.json();
        const mapped: ScanJobUI[] = Array.isArray(data?.jobs)
          ? data.jobs.map((j: ScanJob) => mapToUI(j))
          : [];
        setJobs(mapped);
      }
      if (statusRes.ok) {
        const rs: RunnerStatus = await statusRes.json();
        setRunnerStatus(rs);
      }
      if (reconRes.ok) {
        const rd = await reconRes.json();
        setLiveRecon(rd.total ?? 0);
      }
      setLastPoll(new Date().toISOString());
      setPulseKey((k) => k + 1);
    } catch { /* auth errors surfaced by authFetch */ } finally {
      setLoading(false);
    }
  }, [authFetch, programId]);

  const loadSchedules = useCallback(async () => {
    try {
      const res = await authFetch(`/programs/${programId}/schedules`);
      if (!res.ok) return;
      const data = await res.json();
      setSchedules(Array.isArray(data?.schedules) ? data.schedules : []);
    } catch { /* schedules panel just stays hidden */ }
  }, [authFetch, programId]);

  // Initial load
  useEffect(() => {
    void loadJobs();
    void loadSchedules();
  }, [loadJobs, loadSchedules]);

  // SSE connection for real-time job updates
  useEffect(() => {
    if (!programId) return;
    let active = true;
    const ctrl = new AbortController();

    async function connectSSE() {
      try {
        const res = await authFetch(`/programs/${programId}/jobs/stream`, {
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        while (active) {
          const { done, value } = await reader.read();
          if (done) break;
          const text = decoder.decode(value);
          for (const line of text.split('\n')) {
            if (line.startsWith('data: ')) {
              try {
                const event = JSON.parse(line.slice(6));
                if (event.type === 'job_update') {
                  void loadJobs();
                }
              } catch { /* ignore malformed */ }
            }
          }
        }
      } catch {
        // Connection dropped — polling takes over
      }
      if (active) setTimeout(connectSSE, 3000);
    }

    void connectSSE();
    return () => { active = false; ctrl.abort(); };
  }, [programId, authFetch, loadJobs]);

  // Adaptive polling: 5s while any jobs are active, 30s when idle
  useEffect(() => {
    const hasActive = () =>
      jobsRef.current.some((j) => j.status === "pending" || j.status === "running");
    let timerId: ReturnType<typeof setTimeout>;
    function scheduleNext() {
      timerId = setTimeout(() => {
        void loadJobs();
        scheduleNext();
      }, hasActive() ? POLL_ACTIVE_MS : POLL_IDLE_MS);
    }
    scheduleNext();
    return () => clearTimeout(timerId);
  }, [loadJobs]);

  async function queueJob(spec: {
    tool: string; source: string; config: Record<string, unknown>; targets: number; yieldKind: string;
    interval?: string;
  }) {
    // Recurring specs become schedules; the backend materializes a job on each due poll
    if (spec.interval) {
      try {
        const res = await authFetch(`/programs/${programId}/schedules`, {
          method: "POST",
          body: JSON.stringify({
            tool_type:     spec.tool,
            target_source: spec.source,
            config:        spec.config,
            interval:      spec.interval,
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => null) as { detail?: string } | null;
          flash(`Failed to create schedule${err?.detail ? `: ${err.detail}` : "."}`);
          return;
        }
        await loadSchedules();
        flash(`Scheduled ${spec.tool} ${spec.interval} — first run on the runner's next poll.`);
      } catch { flash("Failed to create schedule."); }
      return;
    }

    try {
      const res = await authFetch(`/programs/${programId}/jobs`, {
        method: "POST",
        body: JSON.stringify({
          tool_type:     spec.tool,
          target_source: spec.source,
          config:        spec.config,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null) as { detail?: string } | null;
        flash(`Failed to queue job${err?.detail ? `: ${err.detail}` : "."}`);
        return;
      }
      const created: ScanJob = await res.json();
      const ui = mapToUI(created);
      setJobs((p) => [ui, ...p]);
      setActiveId(ui.id);
      flash("Job queued. Run `vardrrunner jobs run` to execute.");
    } catch { flash("Failed to queue job."); }
  }

  async function toggleSchedule(id: string, enabled: boolean) {
    try {
      const res = await authFetch(`/programs/${programId}/schedules/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) { flash("Failed to update schedule."); return; }
      const updated: ScheduledScan = await res.json();
      setSchedules((p) => p.map((s) => (s.id === id ? updated : s)));
    } catch { flash("Failed to update schedule."); }
  }

  async function deleteSchedule(id: string) {
    try {
      const res = await authFetch(`/programs/${programId}/schedules/${id}`, { method: "DELETE" });
      if (!res.ok) { flash("Failed to delete schedule."); return; }
      setSchedules((p) => p.filter((s) => s.id !== id));
      flash("Schedule deleted.");
    } catch { flash("Failed to delete schedule."); }
  }

  async function cancel(id: string) {
    try {
      const res = await authFetch(`/jobs/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "failed", error_message: "cancelled by operator" }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null) as { detail?: string } | null;
        flash(`Failed to cancel job${err?.detail ? `: ${err.detail}` : "."}`);
        return;
      }
      const updated: ScanJob = await res.json();
      setJobs((p) => p.map((j) => (j.id === id ? mapToUI(updated) : j)));
      flash("Job cancelled.");
    } catch { flash("Failed to cancel job."); }
  }

  async function retry(id: string) {
    const original = jobsRef.current.find((j) => j.id === id);
    if (!original) return;
    try {
      const res = await authFetch(`/programs/${programId}/jobs`, {
        method: "POST",
        body: JSON.stringify({
          tool_type:     original.tool,
          target_source: original.source,
          config:        original.config,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null) as { detail?: string } | null;
        flash(`Failed to re-queue job${err?.detail ? `: ${err.detail}` : "."}`);
        return;
      }
      const created: ScanJob = await res.json();
      const ui = mapToUI(created);
      setJobs((p) => [ui, ...p]);
      setActiveId(ui.id);
      flash("Job re-queued.");
    } catch { flash("Failed to re-queue job."); }
  }

  async function deleteJob(id: string) {
    try {
      const res = await authFetch(`/jobs/${id}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => null) as { detail?: string } | null;
        flash(`Failed to delete job${err?.detail ? `: ${err.detail}` : "."}`);
        return;
      }
      setJobs((p) => p.filter((j) => j.id !== id));
      if (activeId === id) setActiveId(null);
      flash("Job deleted.");
    } catch { flash("Failed to delete job."); }
  }

  function runPending() {
    if (pendingCount === 0) { flash("No pending jobs."); return; }
    flash(`${pendingCount} job${pendingCount > 1 ? "s" : ""} pending — run \`vardrrunner jobs run\` to execute.`);
  }

  const sorted       = [...jobs].sort((a, b) => new Date(b.queuedAt).getTime() - new Date(a.queuedAt).getTime());
  const activeJob    = jobs.find((j) => j.id === activeId) ?? null;
  const pendingCount = jobs.filter((j) => j.status === "pending").length;
  const runningCount = jobs.filter((j) => j.status === "running").length;
  const busy         = runningCount > 0;

  return (
    <div className="space-y-5">
      {!hideHeader && (
        <div className="border-b border-[#2e2e2e] pb-5">
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
      )}

      <ToastBanner msg={toast} accent={ACCENT} />

      <Bridge
        accent={ACCENT}
        runnerOnline={runnerOnline}
        runnerStatus={runnerStatus}
        autoRun={autoRun}
        lastPoll={lastPoll}
        queueDepth={pendingCount}
        runningCount={runningCount}
        busy={busy}
        pulseKey={pulseKey}
        collapsed={prefs.collapsed}
        onRefreshRunner={() => { void loadJobs(); }}
        onToggleAuto={() => setAutoRun((v) => !v)}
        onToggleCollapse={() => pref("collapsed", !prefs.collapsed)}
        onSetupRunner={() => navigate("settings")}
      />

      <Telemetry jobs={jobs} accent={ACCENT} />

      <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
        <div className="space-y-5">
          <Composer
            key={`${defaultTool ?? ""}:${prefillEpoch ?? 0}`}
            accent={ACCENT}
            onQueue={queueJob}
            runnerOnline={runnerOnline}
            scopeCount={scopeCount}
            reconCount={reconCount}
            programName={programName}
            initialTool={defaultTool}
          />
          <SchedulesPanel
            accent={ACCENT}
            schedules={schedules}
            onToggle={toggleSchedule}
            onDelete={deleteSchedule}
          />
        </div>

        <div className="space-y-5">
          {loading ? (
            <div className="flex min-h-[160px] items-center gap-2 rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] px-6 font-mono text-sm text-[#52525b]">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ backgroundColor: ACCENT }} />
              loading jobs…
            </div>
          ) : (
            <JobBoard
              jobs={sorted}
              accent={ACCENT}
              view={prefs.view}
              onViewChange={(v) => pref("view", v)}
              activeId={activeId}
              onSelect={(id) => { setActiveId(id); pref("showTerminal", true); }}
              onDelete={deleteJob}
              onRunPending={runPending}
              pendingCount={pendingCount}
              runnerOnline={runnerOnline}
              autoRun={autoRun}
            />
          )}

          {!loading && (prefs.showTerminal ? (
            <Terminal
              job={activeJob}
              accent={ACCENT}
              onClose={() => pref("showTerminal", false)}
              onRetry={retry}
              onCancel={cancel}
              onDelete={deleteJob}
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
          ))}
        </div>
      </div>
    </div>
  );
}
