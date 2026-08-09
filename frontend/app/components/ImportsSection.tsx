"use client";

import { useState } from "react";
import { Engagement } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, PrimaryButton, SectionHeader } from "./ui";

export default function ImportsSection({ engagement }: { engagement: Engagement }) {
  const { authFetch, setMessage, refreshSelectedEngagement } = useAppContext();
  const [toolType,   setToolType]   = useState("ffuf");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [loading,    setLoading]    = useState(false);

  async function handleImport() {
    if (!importFile) return;
    const formData = new FormData();
    formData.append("tool_type", toolType);
    formData.append("file", importFile);
    setLoading(true); setMessage("");
    try {
      const res = await authFetch(`/engagements/${engagement.id}/imports`, { method: "POST", body: formData });
      if (!res.ok) throw new Error();
      setImportFile(null);
      await refreshSelectedEngagement(engagement.id);
      setMessage("Import complete.");
    } catch { setMessage("Import failed."); } finally { setLoading(false); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Imports" description="Upload tool output instead of manually typing recon data." />
      <Panel title="Import Tool Output">
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Tool Type</label>
            <select className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none" value={toolType} onChange={(e) => setToolType(e.target.value)}>
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
        <div className="mt-5"><PrimaryButton onClick={handleImport} label={loading ? "Importing…" : "Import Results"} /></div>
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
  );
}
