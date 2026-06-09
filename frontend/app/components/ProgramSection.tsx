"use client";

import { useEffect, useState } from "react";
import { Program } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, Input, Textarea, PrimaryButton, DangerButton, SectionHeader } from "./ui";

export default function ProgramSection({ program }: { program: Program }) {
  const { authFetch, setMessage, refreshSelectedProgram, deleteProgram } = useAppContext();
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
  // would overwrite edits the user is currently typing in the form.
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

  return (
    <div className="space-y-7">
      <SectionHeader title="Program Profile" description="Track target program details, policies, and notes." />
      <Panel title="Edit Program">
        <div className="grid gap-4 md:grid-cols-2">
          <Input label="Program Name"      value={form.name}               onChange={(v) => setForm({ ...form, name: v })} />
          <Input label="Platform"          value={form.platform}           onChange={(v) => setForm({ ...form, platform: v })} />
          <Input label="Program URL"       value={form.program_url}        onChange={(v) => setForm({ ...form, program_url: v })} />
          <Input label="Severity Guidance" value={form.severity_guidance}  onChange={(v) => setForm({ ...form, severity_guidance: v })} />
        </div>
        <div className="mt-4 grid gap-4">
          <Textarea label="Scope Summary"    value={form.scope_summary}    onChange={(v) => setForm({ ...form, scope_summary: v })} />
          <Textarea label="Safe Harbor Notes" value={form.safe_harbor_notes} onChange={(v) => setForm({ ...form, safe_harbor_notes: v })} />
        </div>
        <div className="mt-5 flex gap-3">
          <PrimaryButton onClick={saveProfile} label="Save Profile" />
          <DangerButton  onClick={deleteProgram} label="Delete Program" />
        </div>
      </Panel>
    </div>
  );
}
