"use client";

import type { ScanJobUI } from "../../types";
import { fmtDur, THROUGHPUT } from "./mockData";

function Sparkline({ data, accent, width = 132, height = 34 }: {
  data: number[]; accent: string; width?: number; height?: number;
}) {
  const max = Math.max(...data, 1);
  const step = width / (data.length - 1);
  const pts = data.map((v, i) => [i * step, height - (v / max) * (height - 4) - 2]);
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  return (
    <svg width={width} height={height} className="overflow-visible">
      <defs>
        <linearGradient id="spark" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.28" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#spark)" />
      <path d={line} fill="none" stroke={accent} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.5" fill={accent} />
    </svg>
  );
}

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
      <div className="rounded-xl border border-[#2e2e2e] bg-[#1a1a1a] px-4 py-3.5">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">Throughput</div>
            <div className="mt-2 font-mono text-2xl font-bold leading-none tracking-tight text-[#f1f5f9]">{avg}</div>
            <div className="mt-1.5 font-mono text-[10px] text-[#52525b]">avg runtime</div>
          </div>
          <div className="pt-1">
            <Sparkline data={THROUGHPUT} accent={accent} />
          </div>
        </div>
      </div>
    </div>
  );
}
