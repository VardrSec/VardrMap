"use client";

import { useEffect, useState } from "react";
import { Engagement } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, Input, Textarea, PrimaryButton, DangerButton, SectionHeader } from "./ui";

export default function ProgramSection({ engagement }: { engagement: Engagement }) {
  const { authFetch, setMessage, refreshSelectedEngagement, deleteEngagement } = useAppContext();
  const [form, setForm] = useState({
    name: engagement.name, platform: engagement.platform, program_url: engagement.program_url,
    scope_summary: engagement.scope_summary, severity_guidance: engagement.severity_guidance,
    safe_harbor_notes: engagement.safe_harbor_notes,
  });

  useEffect(() => {
    setForm({
      name: engagement.name, platform: engagement.platform, program_url: engagement.program_url,
      scope_summary: engagement.scope_summary, severity_guidance: engagement.severity_guidance,
      safe_harbor_notes: engagement.safe_harbor_notes,
    });
  // Intentionally keyed on engagement.id only — re-running on every field change
  // would overwrite edits the user is currently typing in the form.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engagement.id]);

  async function saveProfile() {
    try {
      const res = await authFetch(`/engagements/${engagement.id}`, { method: "PATCH", body: JSON.stringify(form) });
      if (!res.ok) throw new Error();
      await refreshSelectedEngagement(engagement.id);
      setMessage("Engagement saved.");
    } catch { setMessage("Failed to save engagement."); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Engagement Profile" description="Track target engagement details, policies, and notes." />
      <Panel title="Edit Engagement">
        <div className="grid gap-4 md:grid-cols-2">
          <Input label="Engagement Name"      value={form.name}               onChange={(v) => setForm({ ...form, name: v })} />
          <Input label="Platform"          value={form.platform}           onChange={(v) => setForm({ ...form, platform: v })} />
          <Input label="Engagement URL"       value={form.program_url}        onChange={(v) => setForm({ ...form, program_url: v })} />
          <Input label="Severity Guidance" value={form.severity_guidance}  onChange={(v) => setForm({ ...form, severity_guidance: v })} />
        </div>
        <div className="mt-4 grid gap-4">
          <Textarea label="Scope Summary"    value={form.scope_summary}    onChange={(v) => setForm({ ...form, scope_summary: v })} />
          <Textarea label="Safe Harbor Notes" value={form.safe_harbor_notes} onChange={(v) => setForm({ ...form, safe_harbor_notes: v })} />
        </div>
        <div className="mt-5 flex gap-3">
          <PrimaryButton onClick={saveProfile} label="Save Profile" />
          <DangerButton  onClick={deleteEngagement} label="Delete Engagement" />
        </div>
      </Panel>
    </div>
  );
}
