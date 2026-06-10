"use client";

import { useEffect, useState } from "react";
import { Program } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, SectionHeader, Input, Textarea, PrimaryButton, DangerButton } from "./ui";

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

type QuickAction = {
  label: string;
  sub: string;
  onClick: () => void;
};

function QuickActionButton({ label, sub, onClick }: QuickAction) {
  return (
    <button onClick={onClick}
      className="flex flex-col items-start rounded-xl border border-[#2e2e2e] bg-[#1a1a1a] px-4 py-3.5 text-left transition hover:border-[#3a3a3a] hover:bg-[#222] active:scale-[0.98]">
      <span className="text-sm font-semibold text-[#f1f5f9]">{label}</span>
      <span className="mt-0.5 text-[10px] text-[#52525b]">{sub}</span>
    </button>
  );
}

export default function OverviewSection({ program }: { program: Program }) {
  const { authFetch, setMessage, refreshSelectedProgram, deleteProgram, navigate, navigateToDashboard } = useAppContext();

  const [form, setForm] = useState({
    name: program.name, platform: program.platform, program_url: program.program_url,
    scope_summary: program.scope_summary, severity_guidance: program.severity_guidance,
    safe_harbor_notes: program.safe_harbor_notes,
  });

  useEffect(() => {
    setForm({
      name: program.name, platform: program.platform, program_url: program.program_url,
      scope_summary: program.scope_summary, severity_guidance: program.severity_guidance,
      safe_harbor_notes: program.safe_harbor_notes,
    });
  // Intentionally keyed on program.id only — re-running on every field change
  // would overwrite edits the user is currently typing.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [program.id]);

  async function saveProfile() {
    try {
      const res = await authFetch(`/programs/${program.id}`, { method: "PATCH", body: JSON.stringify(form) });
      if (!res.ok) throw new Error();
      await refreshSelectedProgram(program.id);
      setMessage("Program saved.");
    } catch { setMessage("Failed to save program."); }
  }

  const total      = program.findings_count;
  const bySeverity = program.findings_by_severity;
  const byStatus   = program.findings_by_status;
  const closed     = byStatus["closed"] ?? 0;
  const closedPct  = total > 0 ? Math.round((closed / total) * 100) : 0;
  const maxSevCount = Math.max(...SEVERITY_CONFIG.map((s) => bySeverity[s.key] ?? 0), 1);

  const quickActions: QuickAction[] = [
    { label: "Run Subfinder",     sub: "Discover subdomains",        onClick: () => navigateToDashboard("subfinder") },
    { label: "Run HTTPX",         sub: "Probe live hosts",           onClick: () => navigateToDashboard("httpx")     },
    { label: "Run Nuclei",        sub: "Scan for vulnerabilities",   onClick: () => navigateToDashboard("nuclei")    },
    { label: "Import File",       sub: "Upload tool output",         onClick: () => navigateToDashboard("import")    },
    { label: "Add Finding",       sub: "Log a manual finding",       onClick: () => navigate("findings")       },
    { label: "Create Report",     sub: "Draft a submission report",  onClick: () => navigate("reports")        },
  ];

  return (
    <div className="space-y-7">
      <SectionHeader title={program.name} description="Mission control for this program — launch scans, review data, and track findings." />

      {/* Quick actions */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {quickActions.map((a) => (
          <QuickActionButton key={a.label} {...a} />
        ))}
      </div>

      {/* Stats */}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <DashboardCard title="In-Scope Assets" value={program.scope?.in?.length ?? 0}    accent="#f59e0b" />
        <DashboardCard title="Recon Entries"   value={program.recon_count}                accent="#89b4fa" />
        <DashboardCard title="Scan Results"    value={program.scans_count}                accent="#f38ba8" />
        <DashboardCard title="Manual Tests"    value={program.manual_tests_count}         accent="#fab387" />
        <DashboardCard title="Findings"        value={total}                              accent="#f9e2af" />
        <DashboardCard title="Reports"         value={program.reports_count}              accent="#a6e3a1" />
      </div>

      {/* Charts */}
      {total > 0 && (
        <div className="grid gap-5 xl:grid-cols-2">
          <Panel title="Findings by Severity">
            <div className="space-y-2.5">
              {SEVERITY_CONFIG.map(({ key, color, label }) => {
                const count = bySeverity[key] ?? 0;
                const pct   = Math.round((count / maxSevCount) * 100);
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
                  <span className="font-mono text-[#a6e3a1]">{closed} / {total} ({closedPct}%)</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#2e2e2e]">
                  <div className="h-full rounded-full bg-[#a6e3a1] transition-all duration-500"
                    style={{ width: `${closedPct}%` }} />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {STATUS_CONFIG.map(({ status, label, color }) => {
                  const count = byStatus[status] ?? 0;
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

      {/* Imports summary + edit form */}
      <div className="grid gap-5 xl:grid-cols-2">
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

        <Panel title="Edit Program">
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Program Name"      value={form.name}              onChange={(v) => setForm({ ...form, name: v })} />
            <Input label="Platform"          value={form.platform}          onChange={(v) => setForm({ ...form, platform: v })} />
            <Input label="Program URL"       value={form.program_url}       onChange={(v) => setForm({ ...form, program_url: v })} />
            <Input label="Severity Guidance" value={form.severity_guidance} onChange={(v) => setForm({ ...form, severity_guidance: v })} />
          </div>
          <div className="mt-4 grid gap-4">
            <Textarea label="Scope Summary"     value={form.scope_summary}     onChange={(v) => setForm({ ...form, scope_summary: v })} />
            <Textarea label="Safe Harbor Notes" value={form.safe_harbor_notes} onChange={(v) => setForm({ ...form, safe_harbor_notes: v })} />
          </div>
          <div className="mt-5 flex gap-3">
            <PrimaryButton onClick={saveProfile}   label="Save Profile"    />
            <DangerButton  onClick={deleteProgram}  label="Delete Program" />
          </div>
        </Panel>
      </div>
    </div>
  );
}
