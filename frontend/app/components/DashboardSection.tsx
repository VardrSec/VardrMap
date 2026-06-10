"use client";

import { useEffect, useState } from "react";
import { Program } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, PrimaryButton } from "./ui";
import JobsSection from "./JobsSection";

type RunTab = "jobs" | "import";

export default function DashboardSection({ program }: { program: Program }) {
  const { state, dispatch, authFetch, setMessage, refreshSelectedProgram } = useAppContext();

  const [activeTab,   setActiveTab]   = useState<RunTab>("jobs");
  const [prefillTool, setPrefillTool] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!state.runPrefill) return;
    if (state.runPrefill.tab === "import") {
      setActiveTab("import");
    } else {
      if (state.runPrefill.tool) setPrefillTool(state.runPrefill.tool);
      setActiveTab("jobs");
    }
    dispatch({ type: "DASHBOARD_PREFILL_CONSUMED" });
  }, [state.runPrefill, dispatch]);

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
      setImportFile(null);
      await refreshSelectedProgram(program.id);
      setMessage("Import complete.");
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

      {activeTab === "jobs" && (
        <JobsSection programId={program.id} defaultTool={prefillTool} hideHeader />
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
