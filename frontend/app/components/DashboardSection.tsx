"use client";

import { Program } from "../types";
import { Panel, KeyValue, SectionHeader } from "./ui";

function DashboardCard({ title, value, accent }: { title: string; value: number; accent: string }) {
  return (
    <div className="rounded-xl border border-[#2e2e2e] bg-[#1a1a1a] p-5 transition hover:border-[#3a3a3a]">
      <div className="text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">{title}</div>
      <div className="mt-3 font-mono text-4xl font-bold tracking-tight" style={{ color: accent }}>{value}</div>
    </div>
  );
}

export default function DashboardSection({ program }: { program: Program }) {
  return (
    <div className="space-y-7">
      <SectionHeader title={program.name} description="Select a program, confirm scope, import tool output, review recon, validate findings, and draft a report." />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <DashboardCard title="In-Scope Assets"  value={program.scope?.in?.length ?? 0} accent="#f59e0b" />
        <DashboardCard title="Recon Entries"    value={program.recon_count}             accent="#89b4fa" />
        <DashboardCard title="Scan Results"     value={program.scans_count}             accent="#f38ba8" />
        <DashboardCard title="Manual Tests"     value={program.manual_tests?.length ?? 0} accent="#fab387" />
        <DashboardCard title="Findings"         value={program.findings?.length ?? 0}   accent="#f9e2af" />
        <DashboardCard title="Reports"          value={program.reports?.length ?? 0}    accent="#a6e3a1" />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Program Snapshot">
          <KeyValue label="Platform"         value={program.platform || "—"} />
          <KeyValue label="Program URL"      value={program.program_url || "—"} />
          <KeyValue label="Scope Summary"    value={program.scope_summary || "—"} />
          <KeyValue label="Severity Guidance" value={program.severity_guidance || "—"} />
          <KeyValue label="Safe Harbor"      value={program.safe_harbor_notes || "—"} />
        </Panel>
        <Panel title="Imports Summary">
          {program.imports.length === 0 ? (
            <p className="text-sm text-[#3a3a3a]">No imports yet.</p>
          ) : (
            <div className="space-y-2">
              {program.imports.map((item) => (
                <div key={item.id} className="flex items-center justify-between rounded-lg border border-[#2e2e2e] bg-[#161616] px-4 py-3">
                  <span className="font-mono text-xs font-semibold text-[#f59e0b] uppercase">{item.tool_type}</span>
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
