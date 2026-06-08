"use client";

import { useCallback, useEffect, useState } from "react";
import { Program, ManualTest, AuthFetch } from "../types";
import { Panel, Input, Textarea, SelectField, PrimaryButton, DangerButton, StatusBadge, SectionHeader } from "./ui";

type ManualFormState = { title: string; hypothesis: string; payload: string; evidence: string; status: string };
const EMPTY: ManualFormState = { title: "", hypothesis: "", payload: "", evidence: "", status: "new" };

function ManualForm({ value, onChange }: { value: ManualFormState; onChange: (v: ManualFormState) => void }) {
  return (
    <div className="grid gap-3">
      <Input label="Title" value={value.title} onChange={(v) => onChange({ ...value, title: v })} />
      <Textarea label="Hypothesis"              value={value.hypothesis} onChange={(v) => onChange({ ...value, hypothesis: v })} />
      <Textarea label="Payload / Request Notes" value={value.payload}    onChange={(v) => onChange({ ...value, payload: v })} />
      <Textarea label="Evidence"                value={value.evidence}   onChange={(v) => onChange({ ...value, evidence: v })} />
      <SelectField label="Status" value={value.status} onChange={(v) => onChange({ ...value, status: v })}
        options={["new", "in_progress", "validated", "closed"]} />
    </div>
  );
}

export default function ManualSection({ program, authFetch, onRefresh, setMessage }: {
  program: Program;
  authFetch: AuthFetch;
  onRefresh: () => Promise<void>;
  setMessage: (m: string) => void;
}) {
  const [manualTests, setManualTests] = useState<ManualTest[]>([]);
  const [form,        setForm]        = useState<ManualFormState>(EMPTY);
  const [editingId,   setEditingId]   = useState<string | null>(null);
  const [editForm,    setEditForm]    = useState<ManualFormState>(EMPTY);

  const loadManualTests = useCallback(async () => {
    try {
      const res = await authFetch(`/programs/${program.id}/manual-tests`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setManualTests(Array.isArray(data?.manual_tests) ? data.manual_tests : []);
    } catch { setMessage("Failed to load manual tests."); }
  }, [program.id, authFetch, setMessage]);

  useEffect(() => { void loadManualTests(); }, [loadManualTests]);

  async function addManualTest() {
    if (!form.title.trim()) return;
    try {
      const res = await authFetch(`/programs/${program.id}/manual-tests`, { method: "POST", body: JSON.stringify(form) });
      if (!res.ok) throw new Error();
      setForm(EMPTY);
      await loadManualTests();
      await onRefresh();
      setMessage("Manual test added.");
    } catch { setMessage("Failed to add manual test."); }
  }

  async function deleteManualTest(testId: string) {
    try {
      await authFetch(`/programs/${program.id}/manual-tests/${testId}`, { method: "DELETE" });
      await loadManualTests();
      await onRefresh();
      setMessage("Manual test deleted.");
    } catch { setMessage("Failed to delete manual test."); }
  }

  function startEdit(test: ManualTest) {
    setEditingId(test.id);
    setEditForm({ title: test.title, hypothesis: test.hypothesis, payload: test.payload, evidence: test.evidence, status: test.status });
  }

  async function saveEdit(testId: string) {
    try {
      const res = await authFetch(`/programs/${program.id}/manual-tests/${testId}`, { method: "PATCH", body: JSON.stringify(editForm) });
      if (!res.ok) throw new Error();
      setEditingId(null);
      await loadManualTests();
      await onRefresh();
      setMessage("Manual test updated.");
    } catch { setMessage("Failed to update manual test."); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Manual Testing" description="Track hypotheses, payloads, exploitation notes, and evidence." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Add Manual Test Note">
          <ManualForm value={form} onChange={setForm} />
          <div className="mt-3">
            <PrimaryButton onClick={addManualTest} label="Save Manual Test" />
          </div>
        </Panel>
        <Panel title="Saved Manual Tests">
          {manualTests.length === 0 ? (
            <p className="text-sm text-[#3a3a3a]">No manual tests saved yet.</p>
          ) : (
            <div className="space-y-3">
              {manualTests.map((test) =>
                editingId === test.id ? (
                  <div key={test.id} className="rounded-xl border border-[#f59e0b]/30 bg-[#161616] p-4 space-y-3">
                    <ManualForm value={editForm} onChange={setEditForm} />
                    <div className="flex gap-2">
                      <PrimaryButton onClick={() => saveEdit(test.id)} label="Save" />
                      <button onClick={() => setEditingId(null)} className="rounded-md border border-[#2e2e2e] px-4 py-2 text-sm text-[#52525b] transition hover:text-[#94a3b8]">
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div key={test.id} className="rounded-xl border border-[#2e2e2e] bg-[#161616] p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-[#f1f5f9]">{test.title}</div>
                        <div className="mt-1"><StatusBadge status={test.status} /></div>
                      </div>
                      <div className="flex gap-2">
                        <button onClick={() => startEdit(test)} className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                          Edit
                        </button>
                        <DangerButton onClick={() => deleteManualTest(test.id)} label="Delete" small />
                      </div>
                    </div>
                    {test.hypothesis && <p className="mt-3 text-sm text-[#6b7280]">{test.hypothesis}</p>}
                    {test.payload    && <p className="mt-2 font-mono text-xs text-[#52525b]">Payload: {test.payload}</p>}
                    {test.evidence   && <p className="mt-1 text-xs text-[#52525b]">Evidence: {test.evidence}</p>}
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
