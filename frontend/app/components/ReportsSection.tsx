"use client";

import { useState } from "react";
import { Program, AuthFetch } from "../types";
import { Panel, Input, Textarea, PrimaryButton, DangerButton, StatusBadge, SectionHeader } from "./ui";

const EMPTY = { finding_id: "", title: "", summary: "", steps: "", impact: "", remediation: "", cwe: "", cvss: "", status: "draft" };

export default function ReportsSection({ program, authFetch, onRefresh, setMessage }: {
  program: Program;
  authFetch: AuthFetch;
  onRefresh: () => Promise<void>;
  setMessage: (m: string) => void;
}) {
  const [form, setForm] = useState(EMPTY);

  function generatePreview() {
    return `# ${form.title || "Untitled Report"}\n\n## Summary\n${form.summary || ""}\n\n## Steps to Reproduce\n${form.steps || ""}\n\n## Impact\n${form.impact || ""}\n\n## Remediation\n${form.remediation || ""}\n\n## CWE\n${form.cwe || ""}\n\n## CVSS\n${form.cvss || ""}`;
  }

  async function addReport() {
    if (!form.title.trim()) return;
    try {
      const res = await authFetch(`/programs/${program.id}/reports`, { method: "POST", body: JSON.stringify(form) });
      if (!res.ok) throw new Error();
      setForm(EMPTY);
      await onRefresh();
      setMessage("Report saved.");
    } catch { setMessage("Failed to save report."); }
  }

  async function deleteReport(reportId: string) {
    try {
      await authFetch(`/programs/${program.id}/reports/${reportId}`, { method: "DELETE" });
      await onRefresh();
      setMessage("Report deleted.");
    } catch { setMessage("Failed to delete report."); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Reports" description="Draft submission-ready reports from validated findings." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Draft Report">
          <div className="grid gap-3">
            <div>
              <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Link Finding</label>
              <select
                className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none"
                value={form.finding_id}
                onChange={(e) => {
                  const fid = e.target.value;
                  const f = (program.findings ?? []).find((x) => x.id === fid);
                  setForm({ ...form, finding_id: fid, title: f?.title || form.title, summary: f?.summary || form.summary, steps: f?.steps || form.steps, impact: f?.impact || form.impact, remediation: f?.remediation || form.remediation });
                }}
              >
                <option value="">No linked finding</option>
                {(program.findings ?? []).map((f) => <option key={f.id} value={f.id}>{f.title}</option>)}
              </select>
            </div>
            <Input label="Report Title"       value={form.title}       onChange={(v) => setForm({ ...form, title: v })} />
            <Textarea label="Summary"         value={form.summary}     onChange={(v) => setForm({ ...form, summary: v })} />
            <Textarea label="Steps to Reproduce" value={form.steps}    onChange={(v) => setForm({ ...form, steps: v })} />
            <Textarea label="Impact"          value={form.impact}      onChange={(v) => setForm({ ...form, impact: v })} />
            <Textarea label="Remediation"     value={form.remediation} onChange={(v) => setForm({ ...form, remediation: v })} />
            <div className="grid gap-3 md:grid-cols-2">
              <Input label="CWE"  value={form.cwe}  onChange={(v) => setForm({ ...form, cwe: v })} />
              <Input label="CVSS" value={form.cvss} onChange={(v) => setForm({ ...form, cvss: v })} />
            </div>
            <PrimaryButton onClick={addReport} label="Save Report" />
          </div>
        </Panel>
        <Panel title="Report Preview">
          <pre className="whitespace-pre-wrap rounded-lg border border-[#2e2e2e] bg-[#161616] p-4 font-mono text-xs leading-relaxed text-[#6b7280]">
            {generatePreview()}
          </pre>
          <div className="mt-5 space-y-2">
            {(program.reports ?? []).map((report) => (
              <div key={report.id} className="flex items-start justify-between gap-3 rounded-xl border border-[#2e2e2e] bg-[#161616] px-4 py-3">
                <div>
                  <div className="font-semibold text-[#f1f5f9]">{report.title}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <StatusBadge status={report.status} />
                    {report.cwe  && <span className="font-mono text-xs text-[#52525b]">CWE: {report.cwe}</span>}
                    {report.cvss && <span className="font-mono text-xs text-[#52525b]">CVSS: {report.cvss}</span>}
                  </div>
                </div>
                <DangerButton onClick={() => deleteReport(report.id)} label="Delete" small />
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
