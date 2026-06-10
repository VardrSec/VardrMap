"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { JobEvent, ScanJobUI, LogLine } from "../../types";
import { useAppContext } from "../../context/AppContext";
import { TOOLS, fmtClock, fmtDur } from "./mockData";

const LINE_COLOR: Record<string, string> = {
  sys:  "#7f849c",
  info: "#89b4fa",
  out:  "#52525b",
  ok:   "#a6e3a1",
  warn: "#f9e2af",
  err:  "#f87171",
};
const SEV_COLOR: Record<string, string> = {
  critical: "#f38ba8",
  high:     "#fab387",
  medium:   "#f9e2af",
  low:      "#89b4fa",
  info:     "#74c7ec",
};

const PREFIX: Record<string, string> = {
  sys: "›", hit: "✶", err: "✗", ok: "✓",
};

function eventToLogLine(e: JobEvent): LogLine {
  switch (e.kind) {
    case "started":          return { kind: "sys",  text: e.text || "runner claimed job" };
    case "targets_resolved": return { kind: "info", text: e.text };
    case "running":          return { kind: "info", text: e.text };
    case "uploaded":         return { kind: "ok",   text: e.text };
    case "done":             return { kind: "ok",   text: e.text || "job complete" };
    case "failed":           return { kind: "err",  text: e.text };
    default:                 return { kind: "out",  text: e.text };
  }
}

function LogLineRow({ line }: { line: LogLine }) {
  const color = line.kind === "hit"
    ? (SEV_COLOR[line.sev ?? ""] || "#fab387")
    : LINE_COLOR[line.kind] || "#52525b";
  const prefix = PREFIX[line.kind] || "·";
  return (
    <div className="flex gap-2 leading-relaxed">
      <span className="select-none" style={{ color }}>{prefix}</span>
      <span style={{ color, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{line.text}</span>
    </div>
  );
}

function ToolGlyph({ tool, color }: { tool: string; color: string }) {
  return (
    <span className="font-mono text-base leading-none" style={{ color }}>
      {TOOLS[tool]?.glyph || "◆"}
    </span>
  );
}

const POLL_MS = 3000;

type TerminalProps = {
  job: ScanJobUI | null;
  accent: string;
  onClose: () => void;
  onRetry: (id: string) => void;
  onCancel: (id: string) => void;
};

export default function Terminal({ job, accent, onClose, onRetry, onCancel }: TerminalProps) {
  const { authFetch } = useAppContext();
  // Cache tagged with jobId — stale cache from a previous job never renders
  const [eventsCache, setEventsCache] = useState<{ jobId: string; events: JobEvent[] } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const jobId     = job?.id     ?? null;
  const jobStatus = job?.status ?? null;

  const fetchEvents = useCallback(async () => {
    if (!jobId) return;
    try {
      const res = await authFetch(`/jobs/${jobId}/events`);
      if (res.ok) {
        const data = await res.json() as { events?: JobEvent[] };
        setEventsCache({ jobId, events: data.events ?? [] });
      }
    } catch { /* ignore */ }
  }, [jobId, authFetch]);

  useEffect(() => {
    // Use timers so fetchEvents (which calls setState) is never called
    // synchronously in the effect body — avoids react-hooks/set-state-in-effect
    const initTid = setTimeout(() => { void fetchEvents(); }, 0);
    const isActive = jobId && (jobStatus === "pending" || jobStatus === "running");
    const pollTid  = isActive ? setInterval(() => { void fetchEvents(); }, POLL_MS) : undefined;
    return () => {
      clearTimeout(initTid);
      if (pollTid !== undefined) clearInterval(pollTid);
    };
  }, [jobId, jobStatus, fetchEvents]);

  // Only use cached events when they belong to the currently selected job
  const events = eventsCache?.jobId === jobId ? eventsCache.events : [];
  const lines: LogLine[] = events.length > 0
    ? events.map(eventToLogLine)
    : (job?.log ?? []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines.length, jobId]);

  if (!job) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center rounded-2xl border border-dashed border-[#2e2e2e] bg-[#1a1a1a] p-8 text-center">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-[#2e2e2e] bg-[#161616] font-mono text-lg text-[#3a3a3a]">
          ⌥
        </div>
        <p className="mt-3 text-sm text-[#52525b]">Select a job to inspect its live output</p>
        <p className="mt-1 font-mono text-[11px] text-[#3a3a3a]">running jobs stream here in real time</p>
      </div>
    );
  }

  const tool = TOOLS[job.tool];
  const statusColor =
    job.status === "running" ? accent :
    job.status === "done"    ? "#a6e3a1" :
    job.status === "failed"  ? "#f87171" : "#94a3b8";

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-[#2e2e2e] bg-[#0d0d0d]">
      {/* header */}
      <div className="flex items-center gap-3 border-b border-[#2e2e2e] bg-[#1a1a1a] px-4 py-3">
        <ToolGlyph tool={job.tool} color={statusColor} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-[#f1f5f9]">{tool?.label || job.tool}</span>
            <span className="font-mono text-[11px] text-[#3a3a3a]">{job.id}</span>
          </div>
          <div className="font-mono text-[10px] text-[#52525b]">{job.source} · {job.targets} targets</div>
        </div>
        <span className="ml-auto flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest"
          style={{ color: statusColor, borderColor: `${statusColor}55` }}>
          {job.status === "running" && (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ backgroundColor: statusColor }} />
          )}
          {job.status}
        </span>
        <button onClick={onClose}
          className="rounded p-1 text-[#52525b] transition hover:bg-[#2e2e2e] hover:text-[#f1f5f9]"
          title="Close">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* progress strip */}
      <div className="flex items-center gap-3 border-b border-[#2e2e2e] bg-[#161616] px-4 py-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#2e2e2e]">
          <div className="h-full rounded-full transition-all duration-300"
            style={{ width: `${job.progress}%`, backgroundColor: statusColor }} />
        </div>
        <span className="font-mono text-[11px] tabular-nums" style={{ color: statusColor }}>{job.progress}%</span>
        {job.status === "done" && (
          <span className="font-mono text-[11px] text-[#a6e3a1]">{job.yield} {job.yieldKind} · {fmtDur(job.durationMs)}</span>
        )}
        {job.status === "running" && (
          <span className="font-mono text-[11px] text-[#52525b]">live</span>
        )}
      </div>

      {/* console */}
      <div
        ref={scrollRef}
        className="jobs-scroll flex-1 overflow-auto px-4 py-3 font-mono text-[12px] leading-relaxed"
        style={{ maxHeight: 360, minHeight: 240 }}
      >
        {lines.length === 0 ? (
          <div className="flex items-center gap-2 text-[#52525b]">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ backgroundColor: accent }} />
            waiting for runner to claim job…
          </div>
        ) : (
          lines.map((l, i) => <LogLineRow key={i} line={l} />)
        )}
        {job.status === "running" && lines.length > 0 && (
          <div className="mt-0.5 flex items-center gap-1">
            <span className="text-[#52525b]">›</span>
            <span className="inline-block h-3.5 w-2 animate-pulse" style={{ backgroundColor: accent }} />
          </div>
        )}
      </div>

      {/* footer */}
      <div className="flex items-center gap-2 border-t border-[#2e2e2e] bg-[#1a1a1a] px-4 py-2.5">
        <span className="font-mono text-[10px] text-[#52525b]">queued {fmtClock(job.queuedAt)}</span>
        {job.error && (
          <span className="truncate font-mono text-[10px] text-[#f87171]">{job.error}</span>
        )}
        <div className="ml-auto flex gap-2">
          {job.status === "running" && (
            <button onClick={() => onCancel(job.id)}
              className="rounded-md border border-[#3a3a3a] px-3 py-1 font-mono text-[11px] text-[#94a3b8] transition hover:border-[#f87171]/50 hover:text-[#f87171]">
              cancel
            </button>
          )}
          {(job.status === "failed" || job.status === "done") && (
            <button onClick={() => onRetry(job.id)}
              className="rounded-md border px-3 py-1 font-mono text-[11px] transition"
              style={{ borderColor: `${accent}55`, color: accent }}>
              re-queue
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
