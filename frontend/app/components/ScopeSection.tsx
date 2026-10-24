"use client";

import { useState } from "react";
import { Engagement } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, Input, Textarea, PrimaryButton, ListCard, SectionHeader } from "./ui";
import ProposalsPanel from "./ProposalsPanel";

type ImportSummary = {
  in: number; out: number; duplicates: number; skipped: number; total_rows: number;
};
type ImportResult = {
  committed: boolean;
  created: number;
  summary: ImportSummary;
  skipped: { line: number; identifier: string; reason: string }[];
};

function subtitleFor(item: { kind: string; notes: string; max_severity?: string }): string {
  const parts = [item.kind];
  if (item.max_severity) parts.push(`max ${item.max_severity}`);
  if (item.notes) parts.push(item.notes);
  return parts.join(" — ");
}

export default function ScopeSection({ engagement }: { engagement: Engagement }) {
  const { authFetch, setMessage, refreshSelectedEngagement } = useAppContext();
  const [scopeIn,  setScopeIn]  = useState({ value: "", kind: "domain", notes: "" });
  const [scopeOut, setScopeOut] = useState({ value: "", kind: "domain", notes: "" });
  const [csv, setCsv] = useState("");
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);

  async function runImport(commit: boolean) {
    if (!csv.trim()) return;
    setImporting(true);
    try {
      const res = await authFetch(`/engagements/${engagement.id}/scope/import`, {
        method: "POST",
        body: JSON.stringify({ csv, format: "hackerone", commit }),
      });
      const data = await res.json();
      if (!res.ok) { setMessage(data?.detail || "Import failed."); return; }
      if (commit) {
        setPreview(null);
        setCsv("");
        await refreshSelectedEngagement(engagement.id);
        setMessage(`Imported ${data.created} scope item${data.created === 1 ? "" : "s"}.`);
      } else {
        setPreview(data as ImportResult);
      }
    } catch { setMessage("Import failed."); }
    finally { setImporting(false); }
  }

  async function addScopeItem(scopeType: "in" | "out") {
    const payload = scopeType === "in" ? scopeIn : scopeOut;
    if (!payload.value.trim()) return;
    try {
      const res = await authFetch(`/engagements/${engagement.id}/scope/${scopeType}`, { method: "POST", body: JSON.stringify(payload) });
      if (!res.ok) throw new Error();
      if (scopeType === "in") setScopeIn({ value: "", kind: "domain", notes: "" });
      else setScopeOut({ value: "", kind: "domain", notes: "" });
      await refreshSelectedEngagement(engagement.id);
      setMessage("Scope updated.");
    } catch { setMessage("Failed to add scope item."); }
  }

  async function deleteScopeItem(scopeType: "in" | "out", itemId: string) {
    try {
      await authFetch(`/engagements/${engagement.id}/scope/${scopeType}/${itemId}`, { method: "DELETE" });
      await refreshSelectedEngagement(engagement.id);
      setMessage("Scope item deleted.");
    } catch { setMessage("Failed to delete scope item."); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Scope" description="Keep clear in-scope and out-of-scope boundaries before testing." />

      <ProposalsPanel engagement={engagement} />

      <Panel title="Import from a scope CSV">
        <p className="mb-3 text-xs text-muted">
          Paste a HackerOne scope export. Preview shows what will be added before anything is
          saved; out-of-scope rows and per-asset severity caps are mapped automatically. Re-importing
          only adds what is new.
        </p>
        <Textarea
          label="Scope CSV"
          value={csv}
          onChange={(v) => { setCsv(v); setPreview(null); }}
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <PrimaryButton onClick={() => runImport(false)} label={importing ? "Working…" : "Preview"} />
          {preview && (preview.summary.in + preview.summary.out) > 0 && (
            <button
              onClick={() => runImport(true)}
              disabled={importing}
              className="rounded-md border border-[#2e2e2e] px-3 py-2 text-xs text-[#94a3b8] transition hover:border-[#3a3a3a] hover:text-[#f1f5f9]"
            >
              Import {preview.summary.in + preview.summary.out} new item
              {preview.summary.in + preview.summary.out === 1 ? "" : "s"}
            </button>
          )}
        </div>
        {preview && (
          <p className="mt-3 text-[11px] text-muted">
            {preview.summary.in} in-scope · {preview.summary.out} out-of-scope ·{" "}
            {preview.summary.duplicates} already present · {preview.summary.skipped} skipped
            {preview.skipped.length > 0 && (
              <span className="block mt-1 text-[#f87171]">
                Skipped: {preview.skipped.map((s) => `line ${s.line} (${s.reason})`).join(", ")}
              </span>
            )}
          </p>
        )}
      </Panel>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="In-Scope Assets">
          <div className="grid gap-3">
            <Input label="Value" value={scopeIn.value} onChange={(v) => setScopeIn({ ...scopeIn, value: v })} />
            <Input label="Kind"  value={scopeIn.kind}  onChange={(v) => setScopeIn({ ...scopeIn, kind: v })} />
            <Textarea label="Notes" value={scopeIn.notes} onChange={(v) => setScopeIn({ ...scopeIn, notes: v })} />
            <PrimaryButton onClick={() => addScopeItem("in")} label="Add In-Scope Asset" />
          </div>
          <div className="mt-5 space-y-2">
            {(engagement.scope?.in ?? []).map((item) => (
              <ListCard key={item.id} title={item.value} subtitle={subtitleFor(item)} onDelete={() => deleteScopeItem("in", item.id)} />
            ))}
          </div>
        </Panel>
        <Panel title="Out-of-Scope Assets">
          <div className="grid gap-3">
            <Input label="Value" value={scopeOut.value} onChange={(v) => setScopeOut({ ...scopeOut, value: v })} />
            <Input label="Kind"  value={scopeOut.kind}  onChange={(v) => setScopeOut({ ...scopeOut, kind: v })} />
            <Textarea label="Notes" value={scopeOut.notes} onChange={(v) => setScopeOut({ ...scopeOut, notes: v })} />
            <PrimaryButton onClick={() => addScopeItem("out")} label="Add Out-of-Scope Asset" />
          </div>
          <div className="mt-5 space-y-2">
            {(engagement.scope?.out ?? []).map((item) => (
              <ListCard key={item.id} title={item.value} subtitle={subtitleFor(item)} onDelete={() => deleteScopeItem("out", item.id)} />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
