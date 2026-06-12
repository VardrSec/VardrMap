"use client";

import type { ScheduledScan } from "../../types";

type SchedulesPanelProps = {
  accent: string;
  schedules: ScheduledScan[];
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
};

function fmtNext(iso: string | null): string {
  if (!iso) return "—";
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "next poll";
  const mins = Math.round(diff / 60000);
  if (mins < 60) return `in ${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `in ${hours}h`;
  return `in ${Math.round(hours / 24)}d`;
}

export default function SchedulesPanel({ accent, schedules, onToggle, onDelete }: SchedulesPanelProps) {
  if (schedules.length === 0) return null;

  return (
    <div className="rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">
          Recurring Scans
        </h3>
        <span className="font-mono text-[10px] text-[#52525b]">{schedules.length} schedule{schedules.length > 1 ? "s" : ""}</span>
      </div>
      <div className="space-y-1.5">
        {schedules.map((s) => (
          <div key={s.id}
            className="flex items-center gap-3 rounded-lg border border-[#2e2e2e] bg-[#161616] px-3 py-2">
            <button
              onClick={() => onToggle(s.id, !s.enabled)}
              title={s.enabled ? "Pause schedule" : "Resume schedule"}
              className="relative h-4 w-7 flex-shrink-0 rounded-full transition"
              style={{ backgroundColor: s.enabled ? accent : "#2e2e2e" }}>
              <span className="absolute top-0.5 h-3 w-3 rounded-full bg-[#0d0d0d] transition-all"
                style={{ left: s.enabled ? "14px" : "2px" }} />
            </button>
            <span className="font-mono text-xs font-semibold" style={{ color: s.enabled ? "#f1f5f9" : "#52525b" }}>
              {s.tool_type}
            </span>
            <span className="font-mono text-[10px] text-[#52525b]">{s.target_source}</span>
            <span className="rounded border border-[#2e2e2e] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide"
              style={{ color: s.enabled ? accent : "#52525b" }}>
              {s.interval}
            </span>
            <span className="ml-auto font-mono text-[10px] text-[#52525b]">
              {s.enabled ? fmtNext(s.next_run_at) : "paused"}
            </span>
            <button onClick={() => onDelete(s.id)}
              className="flex-shrink-0 rounded-md border border-[#2e2e2e] px-2 py-0.5 font-mono text-[10px] text-[#52525b] transition hover:border-[#f87171]/50 hover:text-[#f87171]"
              title="Delete schedule">
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
