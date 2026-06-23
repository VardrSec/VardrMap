"use client";

import type { ScanJobUI } from "../../types";
import { TOOLS, fmtAgo, fmtDur } from "./mockData";

const STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: "Pending", color: "#94a3b8" },
  running: { label: "Running", color: "#f59e0b" },
  done:    { label: "Done",    color: "#a6e3a1" },
  failed:  { label: "Failed",  color: "#f87171" },
};

function ToolGlyph({ tool, color }: { tool: string; color: string }) {
  return (
    <span className="font-mono text-base leading-none" style={{ color }}>
      {TOOLS[tool]?.glyph || "◆"}
    </span>
  );
}

function StatusChip({ status, accent }: { status: string; accent: string }) {
  const m = STATUS_META[status] ?? STATUS_META.pending;
  const color = status === "running" ? accent : m.color;
  return (
    <span className="inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest"
      style={{ color, borderColor: `${color}44` }}>
      {status === "running" && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ backgroundColor: color }} />
      )}
      {m.label}
    </span>
  );
}

function MiniBar({ progress, color }: { progress: number; color: string }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-[#242424]">
      <div className="h-full rounded-full transition-all duration-300"
        style={{ width: `${progress}%`, backgroundColor: color }} />
    </div>
  );
}

// ---- STREAM VIEW --------------------------------------------------------

function TrashButton({ onClick }: { onClick: (e: React.MouseEvent) => void }) {
  return (
    <button
      onClick={onClick}
      title="Delete job"
      className="flex-shrink-0 rounded p-1 text-[#3a3a3a] opacity-0 transition group-hover:opacity-100 hover:!text-[#f87171]">
      <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
        <path d="M6 2a1 1 0 0 0-1 1H2.5a.5.5 0 0 0 0 1H3v9a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4h.5a.5.5 0 0 0 0-1H11a1 1 0 0 0-1-1H6zm1 4a.5.5 0 0 1 .5.5v5a.5.5 0 0 1-1 0v-5A.5.5 0 0 1 7 6zm2 0a.5.5 0 0 1 .5.5v5a.5.5 0 0 1-1 0v-5A.5.5 0 0 1 9 6z"/>
      </svg>
    </button>
  );
}

function StreamCard({ job, accent, active, onClick, onDelete }: {
  job: ScanJobUI; accent: string; active: boolean; onClick: () => void; onDelete: () => void;
}) {
  const sc = job.status === "running" ? accent : STATUS_META[job.status]?.color ?? "#94a3b8";
  return (
    <div className="group flex w-full items-center gap-3 rounded-xl border px-4 py-3 transition cursor-pointer"
      style={{ borderColor: active ? `${accent}66` : "#2e2e2e", backgroundColor: active ? "#161616" : "#1a1a1a" }}
      onClick={onClick}>
      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-[#2e2e2e] bg-[#161616]">
        <ToolGlyph tool={job.tool} color={sc} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[13px] font-semibold text-[#f1f5f9]">{job.tool}</span>
          <span className="text-[#3a3a3a]">·</span>
          <span className="font-mono text-[11px] text-[#52525b]">{job.source}</span>
          <span className="ml-auto font-mono text-[10px] text-[#3a3a3a]">{fmtAgo(job.queuedAt)}</span>
        </div>
        <div className="mt-1.5 flex items-center gap-2">
          <StatusChip status={job.status} accent={accent} />
          {job.status === "running" ? (
            <div className="flex flex-1 items-center gap-2">
              <MiniBar progress={job.progress} color={sc} />
              <span className="font-mono text-[10px] tabular-nums" style={{ color: sc }}>{job.progress}%</span>
            </div>
          ) : job.status === "done" ? (
            <span className="font-mono text-[11px]" style={{ color: "#a6e3a1" }}>
              {job.yield} {job.yieldKind} · {fmtDur(job.durationMs)}
            </span>
          ) : job.status === "failed" ? (
            <span className="truncate font-mono text-[11px] text-[#f87171]">{job.error || "execution failed"}</span>
          ) : (
            <span className="font-mono text-[11px] text-[#52525b]">{job.targets} targets · awaiting runner</span>
          )}
        </div>
      </div>
      <TrashButton onClick={(e) => { e.stopPropagation(); onDelete(); }} />
    </div>
  );
}

function StreamView({ jobs, accent, activeId, onSelect, onDelete }: ViewProps) {
  return (
    <div className="space-y-2">
      {jobs.map((j) => (
        <StreamCard key={j.id} job={j} accent={accent} active={activeId === j.id} onClick={() => onSelect(j.id)} onDelete={() => onDelete(j.id)} />
      ))}
    </div>
  );
}

// ---- PIPELINE VIEW -------------------------------------------------------

function PipelineCard({ job, accent, active, onClick, onDelete }: {
  job: ScanJobUI; accent: string; active: boolean; onClick: () => void; onDelete: () => void;
}) {
  const sc = job.status === "running" ? accent : STATUS_META[job.status]?.color ?? "#94a3b8";
  return (
    <div onClick={onClick} className="group cursor-pointer rounded-lg border px-2.5 py-2 text-left transition"
      style={{ borderColor: active ? `${accent}66` : "#2e2e2e", backgroundColor: active ? "#161616" : "#1a1a1a" }}>
      <div className="flex items-center gap-1.5">
        <ToolGlyph tool={job.tool} color={sc} />
        <span className="font-mono text-[12px] font-semibold text-[#f1f5f9]">{job.tool}</span>
        <span className="ml-auto font-mono text-[9px] text-[#3a3a3a]">{fmtAgo(job.queuedAt)}</span>
        <TrashButton onClick={(e) => { e.stopPropagation(); onDelete(); }} />
      </div>
      <div className="mt-1 font-mono text-[10px] text-[#52525b]">{job.source} · {job.targets} targets</div>
      {job.status === "running" && <div className="mt-2"><MiniBar progress={job.progress} color={sc} /></div>}
      {job.status === "done" && (
        <div className="mt-1.5 font-mono text-[10px] text-[#a6e3a1]">+{job.yield} {job.yieldKind}</div>
      )}
      {job.status === "failed" && (
        <div className="mt-1.5 truncate font-mono text-[10px] text-[#f87171]">failed</div>
      )}
    </div>
  );
}

function PipelineView({ jobs, accent, activeId, onSelect, onDelete }: ViewProps) {
  const cols: Array<"pending" | "running" | "done" | "failed"> = ["pending", "running", "done", "failed"];
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {cols.map((col) => {
        const items = jobs.filter((j) => j.status === col);
        const m = STATUS_META[col];
        const color = col === "running" ? accent : m.color;
        return (
          <div key={col} className="rounded-xl border border-[#2e2e2e] bg-[#161616]/40 p-2.5">
            <div className="mb-2.5 flex items-center gap-2 px-1">
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
              <span className="font-mono text-[10px] uppercase tracking-widest" style={{ color }}>{m.label}</span>
              <span className="ml-auto font-mono text-[10px] text-[#52525b]">{items.length}</span>
            </div>
            <div className="space-y-2">
              {items.length === 0 ? (
                <div className="rounded-lg border border-dashed border-[#2e2e2e] py-4 text-center font-mono text-[10px] text-[#3a3a3a]">
                  empty
                </div>
              ) : (
                items.map((j) => (
                  <PipelineCard key={j.id} job={j} accent={accent} active={activeId === j.id} onClick={() => onSelect(j.id)} onDelete={() => onDelete(j.id)} />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---- TABLE VIEW -----------------------------------------------------------

function TableView({ jobs, accent, activeId, onSelect, onDelete }: ViewProps) {
  return (
    <div className="overflow-hidden rounded-xl border border-[#2e2e2e]">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-[#161616]">
            {["Tool", "Source", "Status", "Progress", "Targets", "Yield", "Runtime", "Queued", ""].map((h) => (
              <th key={h} className="px-3 py-2 font-mono text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => {
            const sc = j.status === "running" ? accent : STATUS_META[j.status]?.color ?? "#94a3b8";
            return (
              <tr key={j.id} onClick={() => onSelect(j.id)}
                className="group cursor-pointer border-t border-[#2e2e2e] transition hover:bg-[#161616]"
                style={{ backgroundColor: activeId === j.id ? "#161616" : "transparent" }}>
                <td className="px-3 py-2.5">
                  <span className="flex items-center gap-1.5">
                    <ToolGlyph tool={j.tool} color={sc} />
                    <span className="font-mono text-[12px] font-semibold text-[#f1f5f9]">{j.tool}</span>
                  </span>
                </td>
                <td className="px-3 py-2.5 font-mono text-[11px] text-[#94a3b8]">{j.source}</td>
                <td className="px-3 py-2.5"><StatusChip status={j.status} accent={accent} /></td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="w-16"><MiniBar progress={j.progress} color={sc} /></div>
                    <span className="font-mono text-[10px] tabular-nums text-[#52525b]">{j.progress}%</span>
                  </div>
                </td>
                <td className="px-3 py-2.5 font-mono text-[11px] tabular-nums text-[#94a3b8]">{j.targets}</td>
                <td className="px-3 py-2.5 font-mono text-[11px] tabular-nums"
                  style={{ color: j.status === "done" ? "#a6e3a1" : "#52525b" }}>
                  {j.status === "done" ? `+${j.yield}` : "—"}
                </td>
                <td className="px-3 py-2.5 font-mono text-[11px] tabular-nums text-[#52525b]">
                  {j.durationMs ? fmtDur(j.durationMs) : "—"}
                </td>
                <td className="px-3 py-2.5 font-mono text-[10px] text-[#3a3a3a]">{fmtAgo(j.queuedAt)}</td>
                <td className="px-3 py-2.5">
                  <TrashButton onClick={(e) => { e.stopPropagation(); onDelete(j.id); }} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- JOBBOARD ------------------------------------------------------------

type ViewProps = {
  jobs: ScanJobUI[];
  accent: string;
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
};

type JobBoardProps = {
  jobs: ScanJobUI[];
  accent: string;
  view: "stream" | "pipeline" | "table";
  onViewChange: (v: "stream" | "pipeline" | "table") => void;
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRunPending: () => void;
  pendingCount: number;
  runnerOnline: boolean;
  autoRun: boolean;
};

export default function JobBoard({
  jobs, accent, view, onViewChange, activeId, onSelect, onDelete, onRunPending, pendingCount, runnerOnline, autoRun,
}: JobBoardProps) {
  const views = { stream: StreamView, pipeline: PipelineView, table: TableView };
  const View = views[view] ?? StreamView;

  return (
    <div className="rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <h3 className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Job Board</h3>
          <span className="rounded bg-[#2e2e2e] px-1.5 py-0.5 font-mono text-[9px] text-[#94a3b8]">{jobs.length}</span>
        </div>
        <div className="flex items-center gap-3">
          {pendingCount > 0 && !autoRun && (
            <button onClick={onRunPending} disabled={!runnerOnline}
              className="flex items-center gap-2 rounded-md px-3 py-1.5 font-mono text-[11px] font-semibold text-[#161616] transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
              style={{ backgroundColor: accent }}>
              <span className="font-sans">▸</span> vardrrunner jobs run · {pendingCount}
            </button>
          )}
          {autoRun && pendingCount > 0 && (
            <span className="flex items-center gap-1.5 font-mono text-[10px] text-[#52525b]">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ backgroundColor: accent }} />
              auto-running queue
            </span>
          )}
          <div className="flex rounded-lg border border-[#2e2e2e] bg-[#161616] p-0.5">
            {(["stream", "pipeline", "table"] as const).map((v) => (
              <button key={v} onClick={() => onViewChange(v)}
                className="rounded-md px-3 py-1 font-mono text-[10px] uppercase tracking-wider transition"
                style={view === v ? { backgroundColor: "#2e2e2e", color: "#f1f5f9" } : { color: "#52525b" }}>
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>
      <View jobs={jobs} accent={accent} activeId={activeId} onSelect={onSelect} onDelete={onDelete} />
    </div>
  );
}
