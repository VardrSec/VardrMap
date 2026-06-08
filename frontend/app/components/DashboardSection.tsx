"use client";

import { Program } from "../types";
import { Panel, KeyValue, SectionHeader } from "./ui";

const SEVERITY_CONFIG = [
  { key: "critical", color: "#f38ba8", label: "Critical" },
  { key: "high",     color: "#fab387", label: "High"     },
  { key: "medium",   color: "#f9e2af", label: "Medium"   },
  { key: "low",      color: "#89b4fa", label: "Low"      },
  { key: "info",     color: "#74c7ec", label: "Info"     },
] as const;

const STATUS_CONFIG = [
  { status: "new",         label: "New",         color: "#52525b" },
  { status: "candidate",   label: "Candidate",   color: "#74c7ec" },
  { status: "triaged",     label: "Triaged",     color: "#89b4fa" },
  { status: "in_progress", label: "In Progress", color: "#f9e2af" },
  { status: "closed",      label: "Closed",      color: "#a6e3a1" },
] as const;

function DashboardCard({ title, value, accent }: { title: string; value: number; accent: string }) {
  return (
    <div className="rounded-xl border border-[#2e2e2e] bg-[#1a1a1a] p-5 transition hover:border-[#3a3a3a]">
      <div className="text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">{title}</div>
      <div className="mt-3 font-mono text-4xl font-bold tracking-tight" style={{ color: accent }}>{value}</div>
    </div>
  );
}

export default function DashboardSection({ program }: { program: Program }) {
  const findings    = program.findings ?? [];
  const total       = findings.length;
  const closedCount = findings.filter((f) => f.status === "closed").length;
  const closedPct   = total > 0 ? Math.round((closedCount / total) * 100) : 0;
  const maxCount    = Math.max(...SEVERITY_CONFIG.map((s) => findings.filter((f) => f.severity === s.key).length), 1);

  return (
    <div className="space-y-7">
      <SectionHeader title={program.name} description="Select a program, confirm scope, import tool output, review recon, validate findings, and draft a report." />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <DashboardCard title="In-Scope Assets" value={program.scope?.in?.length ?? 0}      accent="#f59e0b" />
        <DashboardCard title="Recon Entries"   value={program.recon_count}                  accent="#89b4fa" />
        <DashboardCard title="Scan Results"    value={program.scans_count}                  accent="#f38ba8" />
        <DashboardCard title="Manual Tests"    value={program.manual_tests?.length ?? 0}    accent="#fab387" />
        <DashboardCard title="Findings"        value={total}                                accent="#f9e2af" />
        <DashboardCard title="Reports"         value={program.reports?.length ?? 0}         accent="#a6e3a1" />
      </div>

      {total > 0 && (
        <div className="grid gap-5 xl:grid-cols-2">
          <Panel title="Findings by Severity">
            <div className="space-y-2.5">
              {SEVERITY_CONFIG.map(({ key, color, label }) => {
                const count = findings.filter((f) => f.severity === key).length;
                const pct   = Math.round((count / maxCount) * 100);
                return (
                  <div key={key} className="flex items-center gap-3">
                    <span className="w-14 flex-shrink-0 text-[11px] font-medium text-[#52525b]">{label}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#2e2e2e]">
                      <div className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${pct}%`, backgroundColor: color }} />
                    </div>
                    <span className="w-5 flex-shrink-0 text-right font-mono text-xs" style={{ color }}>{count}</span>
                  </div>
                );
              })}
            </div>
          </Panel>

          <Panel title="Findings Progress">
            <div className="space-y-4">
              <div>
                <div className="mb-1.5 flex items-center justify-between text-xs">
                  <span className="text-[#52525b]">Resolved</span>
                  <span className="font-mono text-[#a6e3a1]">{closedCount} / {total} ({closedPct}%)</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#2e2e2e]">
                  <div className="h-full rounded-full bg-[#a6e3a1] transition-all duration-500"
                    style={{ width: `${closedPct}%` }} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {STATUS_CONFIG.map(({ status, label, color }) => {
                  const count = findings.filter((f) => f.status === status).length;
                  return (
                    <div key={status} className="flex items-center justify-between rounded-lg border border-[#2e2e2e] bg-[#161616] px-3 py-2">
                      <span className="text-xs text-[#52525b]">{label}</span>
                      <span className="font-mono text-sm font-bold" style={{ color }}>{count}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </Panel>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Program Snapshot">
          <KeyValue label="Platform"          value={program.platform || "—"} />
          <KeyValue label="Program URL"       value={program.program_url || "—"} />
          <KeyValue label="Scope Summary"     value={program.scope_summary || "—"} />
          <KeyValue label="Severity Guidance" value={program.severity_guidance || "—"} />
          <KeyValue label="Safe Harbor"       value={program.safe_harbor_notes || "—"} />
        </Panel>
        <Panel title="Imports Summary">
          {program.imports.length === 0 ? (
            <p className="text-sm text-[#3a3a3a]">No imports yet.</p>
          ) : (
            <div className="space-y-2">
              {program.imports.map((item) => (
                <div key={item.id} className="flex items-center justify-between rounded-lg border border-[#2e2e2e] bg-[#161616] px-4 py-3">
                  <span className="font-mono text-xs font-semibold uppercase text-[#f59e0b]">{item.tool_type}</span>
                  <span className="text-xs text-[#52525b]">{item.imported_count} records</span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
