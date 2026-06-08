"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Program, Report, AuthFetch } from "../types";
import { Panel, Input, Textarea, SelectField, PrimaryButton, DangerButton, StatusBadge, SectionHeader } from "./ui";

type ReportFormState = { finding_id: string; title: string; summary: string; steps: string; impact: string; remediation: string; cwe: string; cvss: string; status: string };
const EMPTY: ReportFormState = { finding_id: "", title: "", summary: "", steps: "", impact: "", remediation: "", cwe: "", cvss: "", status: "draft" };

const MD_CLASSES = `text-sm text-[#6b7280] leading-relaxed space-y-2
  [&_h1]:text-lg [&_h1]:font-semibold [&_h1]:text-[#f1f5f9]
  [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-[#f1f5f9]
  [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-[#94a3b8]
  [&_strong]:text-[#f1f5f9]
  [&_a]:text-[#89b4fa] [&_a]:no-underline hover:[&_a]:underline
  [&_code]:rounded [&_code]:bg-[#2e2e2e] [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_code]:text-[#a6e3a1] [&_code]:font-mono
  [&_pre]:rounded-md [&_pre]:border [&_pre]:border-[#2e2e2e] [&_pre]:bg-[#161616] [&_pre]:p-3 [&_pre]:text-xs
  [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4
  [&_li]:text-[#6b7280]
  [&_blockquote]:border-l-2 [&_blockquote]:border-[#f59e0b]/30 [&_blockquote]:pl-3 [&_blockquote]:text-[#52525b]
  [&_hr]:border-[#2e2e2e]`;

function generateMarkdown(f: ReportFormState) {
  return [
    `# ${f.title || "Untitled Report"}`,
    `\n## Summary\n${f.summary || ""}`,
    `\n## Steps to Reproduce\n${f.steps || ""}`,
    `\n## Impact\n${f.impact || ""}`,
    `\n## Remediation\n${f.remediation || ""}`,
    f.cwe  ? `\n## CWE\n${f.cwe}`   : "",
    f.cvss ? `\n## CVSS\n${f.cvss}` : "",
  ].join("");
}

function ReportFields({ value, onChange }: { value: ReportFormState; onChange: (v: ReportFormState) => void }) {
  return (
    <div className="grid gap-3">
      <Input label="Report Title"          value={value.title}       onChange={(v) => onChange({ ...value, title: v })} />
      <Textarea label="Summary"            value={value.summary}     onChange={(v) => onChange({ ...value, summary: v })} />
      <Textarea label="Steps to Reproduce" value={value.steps}       onChange={(v) => onChange({ ...value, steps: v })} />
      <Textarea label="Impact"             value={value.impact}      onChange={(v) => onChange({ ...value, impact: v })} />
      <Textarea label="Remediation"        value={value.remediation} onChange={(v) => onChange({ ...value, remediation: v })} />
      <div className="grid gap-3 md:grid-cols-2">
        <Input label="CWE"  value={value.cwe}  onChange={(v) => onChange({ ...value, cwe: v })} />
        <Input label="CVSS" value={value.cvss} onChange={(v) => onChange({ ...value, cvss: v })} />
      </div>
      <SelectField label="Status" value={value.status} onChange={(v) => onChange({ ...value, status: v })}
        options={["draft", "submitted", "accepted", "duplicate", "informative", "resolved"]} />
    </div>
  );
}

export default function ReportsSection({ program, authFetch, onRefresh, setMessage }: {
  program: Program;
  authFetch: AuthFetch;
  onRefresh: () => Promise<void>;
  setMessage: (m: string) => void;
}) {
  const [form,      setForm]      = useState<ReportFormState>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm,  setEditForm]  = useState<ReportFormState>(EMPTY);

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(generateMarkdown(form));
      setMessage("Copied to clipboard.");
    } catch { setMessage("Failed to copy."); }
  }

  function downloadMarkdown() {
    const content = generateMarkdown(form);
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(form.title || "report").replace(/[^a-z0-9]/gi, "-").toLowerCase()}.md`;
    a.click();
    URL.revokeObjectURL(url);
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

  function startEdit(report: Report) {
    setEditingId(report.id);
    setEditForm({ finding_id: report.finding_id, title: report.title, summary: report.summary, steps: report.steps, impact: report.impact, remediation: report.remediation, cwe: report.cwe, cvss: report.cvss, status: report.status });
  }

  async function saveEdit(reportId: string) {
    try {
      const res = await authFetch(`/programs/${program.id}/reports/${reportId}`, { method: "PATCH", body: JSON.stringify(editForm) });
      if (!res.ok) throw new Error();
      setEditingId(null);
      await onRefresh();
      setMessage("Report updated.");
    } catch { setMessage("Failed to update report."); }
  }

  const mdPreview = generateMarkdown(form);

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
            <ReportFields value={form} onChange={setForm} />
            <PrimaryButton onClick={addReport} label="Save Report" />
          </div>
        </Panel>

        <Panel title="Report Preview">
          <div className="min-h-[140px] rounded-lg border border-[#2e2e2e] bg-[#161616] p-4">
            {form.title ? (
              <div className={MD_CLASSES}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{mdPreview}</ReactMarkdown>
              </div>
            ) : (
              <p className="text-xs text-[#3a3a3a] italic">Fill in the draft to see a preview.</p>
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <button onClick={copyMarkdown} className="rounded-md border border-[#2e2e2e] px-3 py-1.5 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
              Copy MD
            </button>
            <button onClick={downloadMarkdown} className="rounded-md border border-[#2e2e2e] px-3 py-1.5 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
              Download .md
            </button>
          </div>

          <div className="mt-5 space-y-2">
            {(program.reports ?? []).map((report) =>
              editingId === report.id ? (
                <div key={report.id} className="rounded-xl border border-[#f59e0b]/30 bg-[#161616] p-4 space-y-3">
                  <ReportFields value={editForm} onChange={setEditForm} />
                  <div className="flex gap-2">
                    <PrimaryButton onClick={() => saveEdit(report.id)} label="Save" />
                    <button onClick={() => setEditingId(null)} className="rounded-md border border-[#2e2e2e] px-4 py-2 text-sm text-[#52525b] transition hover:text-[#94a3b8]">
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div key={report.id} className="flex items-start justify-between gap-3 rounded-xl border border-[#2e2e2e] bg-[#161616] px-4 py-3">
                  <div>
                    <div className="font-semibold text-[#f1f5f9]">{report.title}</div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <StatusBadge status={report.status} />
                      {report.cwe  && <span className="font-mono text-xs text-[#52525b]">CWE: {report.cwe}</span>}
                      {report.cvss && <span className="font-mono text-xs text-[#52525b]">CVSS: {report.cvss}</span>}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => startEdit(report)} className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                      Edit
                    </button>
                    <DangerButton onClick={() => deleteReport(report.id)} label="Delete" small />
                  </div>
                </div>
              )
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
