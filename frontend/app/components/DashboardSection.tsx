"use client";

import { useEffect, useState } from "react";
import { Program } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, PrimaryButton } from "./ui";
import JobsSection from "./JobsSection";

type RunTab = "jobs" | "import";

type Stats = {
  findings_total: number;
  findings_by_severity: Record<string, number>;
  submissions_total: number;
  submissions_accepted: number;
  submissions_paid: number;
  recon_total: number;
};

export default function DashboardSection({ program }: { program: Program }) {
  const { state, dispatch, authFetch, setMessage, refreshSelectedProgram, navigate } = useAppContext();

  const [activeTab,   setActiveTab]   = useState<RunTab>("jobs");
  const [prefillTool, setPrefillTool] = useState<string | undefined>(undefined);
  const [stats,       setStats]       = useState<Stats | null>(null);
  const [prefillEpoch, setPrefillEpoch] = useState(0);

  useEffect(() => {
    if (!state.dashboardPrefill) return;
    if (state.dashboardPrefill.tab === "import") {
      setActiveTab("import");
    } else {
      if (state.dashboardPrefill.tool) {
        setPrefillTool(state.dashboardPrefill.tool);
        setPrefillEpoch((n) => n + 1);
      }
      setActiveTab("jobs");
    }
    dispatch({ type: "DASHBOARD_PREFILL_CONSUMED" });
  }, [state.dashboardPrefill, dispatch]);

  useEffect(() => {
    void Promise.all([
      authFetch(`/programs/${program.id}/findings?limit=1&offset=0`),
      authFetch(`/programs/${program.id}/submissions`),
      authFetch(`/programs/${program.id}/recon?limit=1`),
    ]).then(async ([fRes, sRes, rRes]) => {
      const fData = fRes.ok ? await fRes.json() : null;
      const sData = sRes.ok ? await sRes.json() : null;
      const rData = rRes.ok ? await rRes.json() : null;
      const subs: { severity: string }[] = fData?.findings ?? [];
      const allSubs: { status: string }[] = sData?.submissions ?? [];
      const bySev: Record<string, number> = {};
      subs.forEach((f) => { bySev[f.severity] = (bySev[f.severity] ?? 0) + 1; });
      setStats({
        findings_total:        fData?.total ?? 0,
        findings_by_severity:  bySev,
        submissions_total:     sData?.total ?? allSubs.length,
        submissions_accepted:  allSubs.filter((s) => s.status === "accepted" || s.status === "paid").length,
        submissions_paid:      allSubs.filter((s) => s.status === "paid").length,
        recon_total:           rData?.total ?? 0,
      });
    });
  }, [program.id, authFetch]);

  const [toolType,    setToolType]    = useState("ffuf");
  const [importFile,  setImportFile]  = useState<File | null>(null);
  const [importing,   setImporting]   = useState(false);

  async function handleImport() {
    if (!importFile) return;
    const formData = new FormData();
    formData.append("tool_type", toolType);
    formData.append("file", importFile);
    setImporting(true);
    setMessage("");
    try {
      const res = await authFetch(`/programs/${program.id}/imports`, { method: "POST", body: formData });
      if (!res.ok) throw new Error();
      const data = await res.json().catch(() => ({}));
      setImportFile(null);
      await refreshSelectedProgram(program.id);
      const newCount = data.new_count ?? 0;
      const updatedCount = data.updated_count ?? 0;
      setMessage(
        toolType === "httpx"
          ? `Import complete — ${newCount} new, ${updatedCount} enriched.`
          : `Import complete — ${data.imported_count ?? 0} imported.`,
      );
    } catch { setMessage("Import failed."); } finally { setImporting(false); }
  }

  const TABS: { id: RunTab; label: string }[] = [
    { id: "jobs",   label: "Jobs"   },
    { id: "import", label: "Import" },
  ];

  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-[#2e2e2e] pb-5">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[#f1f5f9]">Dashboard</h2>
          <p className="mt-1.5 text-sm text-[#52525b]">
            Dispatch scan jobs to VardrRunner or import tool output directly.
          </p>
        </div>
        <div className="flex rounded-lg border border-[#2e2e2e] bg-[#1a1a1a] p-0.5">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              className="rounded-md px-5 py-1.5 font-mono text-[11px] uppercase tracking-wider transition"
              style={activeTab === t.id ? { backgroundColor: "#2e2e2e", color: "#f1f5f9" } : { color: "#52525b" }}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Program stats */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: "Recon assets",  value: stats.recon_total,          section: "review"      as const },
            { label: "Findings",      value: stats.findings_total,        section: "findings"    as const },
            { label: "Accepted",      value: stats.submissions_accepted,  section: "submissions" as const },
            { label: "Paid",          value: stats.submissions_paid,      section: "submissions" as const },
          ].map(({ label, value, section }) => (
            <button
              key={label}
              onClick={() => navigate(section)}
              className="group flex flex-col items-start rounded-xl border border-[#2e2e2e] bg-[#161616] px-4 py-3 text-left transition hover:border-[#3a3a3a]">
              <span className="font-mono text-2xl font-bold text-[#f1f5f9]">{value}</span>
              <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-widest text-[#52525b] group-hover:text-[#6b7280]">{label}</span>
            </button>
          ))}
        </div>
      )}

      {stats && stats.findings_total > 0 && (
        <div className="flex flex-wrap gap-2">
          {["critical", "high", "medium", "low", "info"]
            .filter((sev) => stats.findings_by_severity[sev])
            .map((sev) => {
              const COLOR: Record<string, string> = { critical: "text-[#f38ba8]", high: "text-[#fab387]", medium: "text-[#f9e2af]", low: "text-[#89b4fa]", info: "text-[#74c7ec]" };
              return (
                <button
                  key={sev}
                  onClick={() => navigate("findings")}
                  className="flex items-center gap-1.5 rounded-full border border-[#2e2e2e] bg-[#161616] px-3 py-1 text-xs transition hover:border-[#3a3a3a]">
                  <span className={`font-mono font-semibold ${COLOR[sev]}`}>{stats.findings_by_severity[sev]}</span>
                  <span className="text-[#52525b]">{sev}</span>
                </button>
              );
            })}
        </div>
      )}

      {activeTab === "jobs" && (
        <JobsSection programId={program.id} defaultTool={prefillTool} prefillEpoch={prefillEpoch} hideHeader />
      )}

      {activeTab === "import" && (
        <div className="space-y-7">
          <Panel title="Import Tool Output">
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Tool Type</label>
                <select
                  className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none"
                  value={toolType} onChange={(e) => setToolType(e.target.value)}>
                  <option value="ffuf">ffuf</option>
                  <option value="httpx">httpx</option>
                  <option value="nuclei">nuclei</option>
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">JSON / JSONL File</label>
                <input type="file" accept=".json,.jsonl,application/json,application/x-ndjson"
                  onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                  className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#52525b] file:mr-3 file:rounded file:border-0 file:bg-[#2e2e2e] file:px-2.5 file:py-1 file:text-xs file:font-semibold file:text-[#f1f5f9]" />
              </div>
            </div>
            <div className="mt-5">
              <PrimaryButton onClick={handleImport} label={importing ? "Importing…" : "Import Results"} />
            </div>
            <div className="mt-6 rounded-xl border border-[#2e2e2e] bg-[#161616] p-4">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Supported imports</p>
              <div className="space-y-1 text-xs text-[#52525b]">
                <p><span className="font-mono text-[#f59e0b]">ffuf</span> — Recon endpoints and paths</p>
                <p><span className="font-mono text-[#f59e0b]">httpx</span> — Live hosts, titles, technologies</p>
                <p><span className="font-mono text-[#f59e0b]">nuclei</span> — Candidate scan findings</p>
              </div>
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}
