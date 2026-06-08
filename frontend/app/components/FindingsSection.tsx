"use client";

import { useEffect, useState } from "react";
import { Program, AuthFetch, Finding, FindingFormState } from "../types";
import { Panel, Input, Textarea, SelectField, PrimaryButton, DangerButton, SeverityBadge, StatusBadge, SectionHeader } from "./ui";

const EMPTY: FindingFormState = { title: "", severity: "medium", asset: "", status: "new", summary: "", steps: "", impact: "", remediation: "" };

function FindingForm({ value, onChange }: { value: FindingFormState; onChange: (v: FindingFormState) => void }) {
  return (
    <div className="grid gap-3">
      <Input label="Title" value={value.title} onChange={(v) => onChange({ ...value, title: v })} />
      <div className="grid gap-3 md:grid-cols-3">
        <SelectField label="Severity" value={value.severity} onChange={(v) => onChange({ ...value, severity: v })}
          options={["info", "low", "medium", "high", "critical"]} />
        <Input label="Asset" value={value.asset} onChange={(v) => onChange({ ...value, asset: v })} />
        <SelectField label="Status" value={value.status} onChange={(v) => onChange({ ...value, status: v })}
          options={["new", "candidate", "triaged", "in_progress", "closed"]} />
      </div>
      <Textarea label="Summary"     value={value.summary}     onChange={(v) => onChange({ ...value, summary: v })} />
      <Textarea label="Steps"       value={value.steps}       onChange={(v) => onChange({ ...value, steps: v })} />
      <Textarea label="Impact"      value={value.impact}      onChange={(v) => onChange({ ...value, impact: v })} />
      <Textarea label="Remediation" value={value.remediation} onChange={(v) => onChange({ ...value, remediation: v })} />
    </div>
  );
}

export default function FindingsSection({ program, authFetch, onRefresh, setMessage, prefill, onPrefillConsumed }: {
  program: Program;
  authFetch: AuthFetch;
  onRefresh: () => Promise<void>;
  setMessage: (m: string) => void;
  prefill: FindingFormState | null;
  onPrefillConsumed: () => void;
}) {
  const [form,      setForm]      = useState<FindingFormState>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm,  setEditForm]  = useState<FindingFormState>(EMPTY);

  // Apply the prefill from a promoted scan, then immediately tell the parent to
  // clear it. If we didn't clear it, navigating away and back to this section
  // would re-apply the old scan data on top of whatever the user typed.
  useEffect(() => {
    if (prefill) {
      setForm(prefill);
      onPrefillConsumed();
    }
  }, [prefill, onPrefillConsumed]);

  async function addFinding() {
    if (!form.title.trim()) return;
    try {
      const res = await authFetch(`/programs/${program.id}/findings`, { method: "POST", body: JSON.stringify(form) });
      if (!res.ok) throw new Error();
      setForm(EMPTY);
      await onRefresh();
      setMessage("Finding added.");
    } catch { setMessage("Failed to add finding."); }
  }

  async function deleteFinding(findingId: string) {
    try {
      await authFetch(`/programs/${program.id}/findings/${findingId}`, { method: "DELETE" });
      await onRefresh();
      setMessage("Finding deleted.");
    } catch { setMessage("Failed to delete finding."); }
  }

  function startEdit(finding: Finding) {
    setEditingId(finding.id);
    setEditForm({ title: finding.title, severity: finding.severity, asset: finding.asset, status: finding.status, summary: finding.summary, steps: finding.steps, impact: finding.impact, remediation: finding.remediation });
  }

  async function saveEdit(findingId: string) {
    try {
      const res = await authFetch(`/programs/${program.id}/findings/${findingId}`, { method: "PATCH", body: JSON.stringify(editForm) });
      if (!res.ok) throw new Error();
      setEditingId(null);
      await onRefresh();
      setMessage("Finding updated.");
    } catch { setMessage("Failed to update finding."); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Findings" description="Track validated issues before drafting the final report." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Add Finding">
          <FindingForm value={form} onChange={setForm} />
          <div className="mt-3">
            <PrimaryButton onClick={addFinding} label="Save Finding" />
          </div>
        </Panel>
        <Panel title="Finding Tracker">
          {(program.findings ?? []).length === 0 ? (
            <p className="text-sm text-[#3a3a3a]">No findings yet.</p>
          ) : (
            <div className="space-y-3">
              {(program.findings ?? []).map((finding) =>
                editingId === finding.id ? (
                  <div key={finding.id} className="rounded-xl border border-[#f59e0b]/30 bg-[#161616] p-4 space-y-3">
                    <FindingForm value={editForm} onChange={setEditForm} />
                    <div className="flex gap-2">
                      <PrimaryButton onClick={() => saveEdit(finding.id)} label="Save" />
                      <button onClick={() => setEditingId(null)} className="rounded-md border border-[#2e2e2e] px-4 py-2 text-sm text-[#52525b] transition hover:text-[#94a3b8]">
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div key={finding.id} className="rounded-xl border border-[#2e2e2e] bg-[#161616] p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="font-semibold text-[#f1f5f9]">{finding.title}</div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <SeverityBadge severity={finding.severity} />
                          <StatusBadge   status={finding.status} />
                          {finding.asset && <span className="font-mono text-xs text-[#52525b]">{finding.asset}</span>}
                          {finding.created_at && (
                            <span className="font-mono text-xs text-[#3a3a3a]">
                              {new Date(finding.created_at).toLocaleDateString()}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button onClick={() => startEdit(finding)} className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                          Edit
                        </button>
                        <DangerButton onClick={() => deleteFinding(finding.id)} label="Delete" small />
                      </div>
                    </div>
                    {finding.summary && <p className="mt-3 text-sm text-[#6b7280]">{finding.summary}</p>}
                  </div>
                )
              )}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
