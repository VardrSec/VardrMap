"use client";

import { useState } from "react";
import { Program, AuthFetch } from "../types";
import { Panel, Input, Textarea, SelectField, PrimaryButton, DangerButton, StatusBadge, SectionHeader } from "./ui";

const EMPTY = { title: "", hypothesis: "", payload: "", evidence: "", status: "new" };

export default function ManualSection({ program, authFetch, onRefresh, setMessage }: {
  program: Program;
  authFetch: AuthFetch;
  onRefresh: () => Promise<void>;
  setMessage: (m: string) => void;
}) {
  const [form, setForm] = useState(EMPTY);

  async function addManualTest() {
    if (!form.title.trim()) return;
    try {
      const res = await authFetch(`/programs/${program.id}/manual-tests`, { method: "POST", body: JSON.stringify(form) });
      if (!res.ok) throw new Error();
      setForm(EMPTY);
      await onRefresh();
      setMessage("Manual test added.");
    } catch { setMessage("Failed to add manual test."); }
  }

  async function deleteManualTest(testId: string) {
    try {
      await authFetch(`/programs/${program.id}/manual-tests/${testId}`, { method: "DELETE" });
      await onRefresh();
      setMessage("Manual test deleted.");
    } catch { setMessage("Failed to delete manual test."); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Manual Testing" description="Track hypotheses, payloads, exploitation notes, and evidence." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Add Manual Test Note">
          <div className="grid gap-3">
            <Input label="Title" value={form.title} onChange={(v) => setForm({ ...form, title: v })} />
            <Textarea label="Hypothesis"              value={form.hypothesis} onChange={(v) => setForm({ ...form, hypothesis: v })} />
            <Textarea label="Payload / Request Notes" value={form.payload}    onChange={(v) => setForm({ ...form, payload: v })} />
            <Textarea label="Evidence"                value={form.evidence}   onChange={(v) => setForm({ ...form, evidence: v })} />
            <SelectField label="Status" value={form.status} onChange={(v) => setForm({ ...form, status: v })}
              options={["new", "in_progress", "validated", "closed"]} />
            <PrimaryButton onClick={addManualTest} label="Save Manual Test" />
          </div>
        </Panel>
        <Panel title="Saved Manual Tests">
          {(program.manual_tests ?? []).length === 0 ? (
            <p className="text-sm text-[#3a3a3a]">No manual tests saved yet.</p>
          ) : (
            <div className="space-y-3">
              {(program.manual_tests ?? []).map((test) => (
                <div key={test.id} className="rounded-xl border border-[#2e2e2e] bg-[#161616] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-[#f1f5f9]">{test.title}</div>
                      <div className="mt-1"><StatusBadge status={test.status} /></div>
                    </div>
                    <DangerButton onClick={() => deleteManualTest(test.id)} label="Delete" small />
                  </div>
                  {test.hypothesis && <p className="mt-3 text-sm text-[#6b7280]">{test.hypothesis}</p>}
                  {test.payload    && <p className="mt-2 font-mono text-xs text-[#52525b]">Payload: {test.payload}</p>}
                  {test.evidence   && <p className="mt-1 text-xs text-[#52525b]">Evidence: {test.evidence}</p>}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
