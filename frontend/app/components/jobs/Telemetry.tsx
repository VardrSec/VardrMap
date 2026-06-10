"use client";

import type { ScanJobUI } from "../../types";
import { fmtDur } from "./mockData";

function StatTile({ label, value, accent, foot }: {
  label: string; value: string | number; accent: string; foot?: string;
}) {
  return (
    <div className="rounded-xl border border-[#2e2e2e] bg-[#1a1a1a] px-4 py-3.5 transition hover:border-[#3a3a3a]">
      <div className="text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">{label}</div>
      <div className="mt-2 font-mono text-2xl font-bold leading-none tracking-tight" style={{ color: accent }}>{value}</div>
      {foot && <div className="mt-1.5 font-mono text-[10px] text-[#52525b]">{foot}</div>}
    </div>
  );
}

export default function Telemetry({ jobs, accent }: { jobs: ScanJobUI[]; accent: string }) {
  const done    = jobs.filter((j) => j.status === "done");
  const failed  = jobs.filter((j) => j.status === "failed").length;
  const running = jobs.filter((j) => j.status === "running").length;
  const pending = jobs.filter((j) => j.status === "pending").length;
  const yielded = done.reduce((a, j) => a + (j.yield || 0), 0);
  const avg     = done.length
    ? fmtDur(done.reduce((a, j) => a + (j.durationMs || 0), 0) / done.length)
    : "—";
  const successRate = done.length + failed > 0
    ? Math.round((done.length / (done.length + failed)) * 100)
    : 100;

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <StatTile label="Running" value={running} accent={accent} foot={`${pending} pending in queue`} />
      <StatTile label="Completed" value={done.length} accent="#a6e3a1" foot={`${failed} failed · ${successRate}% success`} />
      <StatTile label="Results Yielded" value={yielded} accent="#89b4fa" foot="pushed to recon + scan" />
      <StatTile label="Avg Runtime" value={avg} accent="#f1f5f9" foot={`across ${done.length} completed job${done.length === 1 ? "" : "s"}`} />
    </div>
  );
}
