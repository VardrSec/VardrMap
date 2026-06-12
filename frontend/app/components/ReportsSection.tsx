"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Program, Finding, Report, ReportFormState } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, Input, Textarea, SelectField, PrimaryButton, DangerButton, StatusBadge, SectionHeader } from "./ui";

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

export default function ReportsSection({ program }: { program: Program }) {
  const {
    authFetch, setMessage, refreshSelectedProgram, promoteToSubmission,
    state: { reportPrefill }, dispatch,
  } = useAppContext();
  const [reports,     setReports]     = useState<Report[]>([]);
  const [total,       setTotal]       = useState(0);
  const [offset,      setOffset]      = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [findings,    setFindings]    = useState<Finding[]>([]);
  const [form,        setForm]        = useState<ReportFormState>(EMPTY);
  const [editingId,   setEditingId]   = useState<string | null>(null);
  const [editForm,    setEditForm]    = useState<ReportFormState>(EMPTY);

  const PAGE = 50;

  const loadReports = useCallback(async () => {
    try {
      const res = await authFetch(`/programs/${program.id}/reports?limit=${PAGE}&offset=0`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setReports(Array.isArray(data?.reports) ? data.reports : []);
      setTotal(data?.total ?? 0);
      setOffset(0);
    } catch { setMessage("Failed to load reports."); }
  }, [program.id, authFetch, setMessage]);

  async function loadMore() {
    const next = offset + PAGE;
    setLoadingMore(true);
    try {
      const res = await authFetch(`/programs/${program.id}/reports?limit=${PAGE}&offset=${next}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setReports((prev) => [...prev, ...(Array.isArray(data?.reports) ? data.reports : [])]);
      setOffset(next);
    } catch { setMessage("Failed to load more reports."); } finally { setLoadingMore(false); }
  }

  const loadFindings = useCallback(async () => {
    try {
      const res = await authFetch(`/programs/${program.id}/findings`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setFindings(Array.isArray(data?.findings) ? data.findings : []);
    } catch { /* non-blocking — dropdown just stays empty */ }
  }, [program.id, authFetch]);

  useEffect(() => {
    void loadReports();
    void loadFindings();
  }, [loadReports, loadFindings]);

  useEffect(() => {
    if (reportPrefill) {
      setForm(reportPrefill);
      dispatch({ type: "REPORT_PREFILL_CONSUMED" });
    }
  }, [reportPrefill, dispatch]);

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

  async function downloadPDF() {
    const { jsPDF } = await import("jspdf");
    const doc = new jsPDF({ unit: "mm", format: "a4" });
    const margin = 20;
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const maxW = pageW - margin * 2;
    let y = margin;

    function needsPage(lines: number, lh = 5) {
      if (y + lines * lh > pageH - margin) { doc.addPage(); y = margin; }
    }

    function section(label: string, body: string) {
      if (!body.trim()) return;
      needsPage(3);
      doc.setFontSize(11); doc.setFont("helvetica", "bold");
      doc.text(label, margin, y); y += 6;
      doc.setFontSize(9); doc.setFont("helvetica", "normal");
      const lines = doc.splitTextToSize(body, maxW);
      needsPage(lines.length);
      doc.text(lines, margin, y); y += lines.length * 5 + 6;
    }

    // Title
    doc.setFontSize(18); doc.setFont("helvetica", "bold");
    const titleLines = doc.splitTextToSize(form.title || "Untitled Report", maxW);
    doc.text(titleLines, margin, y); y += titleLines.length * 8 + 2;

    // Metadata chips
    const meta = [
      form.status && `Status: ${form.status}`,
      form.cwe && `CWE: ${form.cwe}`,
      form.cvss && `CVSS: ${form.cvss}`,
    ].filter(Boolean).join("   ·   ");
    if (meta) {
      doc.setFontSize(8); doc.setFont("helvetica", "normal");
      doc.setTextColor(120, 120, 120);
      doc.text(meta, margin, y); y += 5;
      doc.setTextColor(0, 0, 0);
    }

    // Divider
    doc.setDrawColor(200, 200, 200);
    doc.line(margin, y, pageW - margin, y); y += 7;

    section("Summary", form.summary);
    section("Steps to Reproduce", form.steps);
    section("Impact", form.impact);
    section("Remediation", form.remediation);

    // Footer
    const footerY = pageH - 10;
    doc.setFontSize(7); doc.setFont("helvetica", "normal");
    doc.setTextColor(160, 160, 160);
    doc.text("Generated by VardrMap", margin, footerY);

    doc.save(`${(form.title || "report").replace(/[^a-z0-9]/gi, "-").toLowerCase()}.pdf`);
  }

  async function addReport() {
    if (!form.title.trim()) return;
    try {
      const res = await authFetch(`/programs/${program.id}/reports`, { method: "POST", body: JSON.stringify(form) });
      if (!res.ok) throw new Error();
      setForm(EMPTY);
      await loadReports();
      await refreshSelectedProgram(program.id);
      setMessage("Report saved.");
    } catch { setMessage("Failed to save report."); }
  }

  async function deleteReport(reportId: string) {
    try {
      await authFetch(`/programs/${program.id}/reports/${reportId}`, { method: "DELETE" });
      await loadReports();
      await refreshSelectedProgram(program.id);
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
      await loadReports();
      await refreshSelectedProgram(program.id);
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
                  const f = findings.find((x) => x.id === fid);
                  setForm({ ...form, finding_id: fid, title: f?.title || form.title, summary: f?.summary || form.summary, steps: f?.steps || form.steps, impact: f?.impact || form.impact, remediation: f?.remediation || form.remediation });
                }}
              >
                <option value="">No linked finding</option>
                {findings.map((f) => <option key={f.id} value={f.id}>{f.title}</option>)}
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
            <button onClick={downloadPDF} className="rounded-md border border-[#2e2e2e] px-3 py-1.5 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
              Export PDF
            </button>
          </div>

          <div className="mt-5 space-y-2">
            {total > 0 && <p className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Saved Reports ({total})</p>}
            {reports.map((report) =>
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
                    <button onClick={() => promoteToSubmission(report)}
                      className="rounded-md border border-[#f59e0b]/40 px-2.5 py-1 text-xs text-[#f59e0b] transition hover:border-[#f59e0b] hover:bg-[#f59e0b]/10"
                      title="Log as a platform submission">
                      Submit →
                    </button>
                    <button onClick={() => startEdit(report)} className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                      Edit
                    </button>
                    <DangerButton onClick={() => deleteReport(report.id)} label="Delete" small />
                  </div>
                </div>
              )
            )}
            {reports.length < total && (
              <button onClick={loadMore} disabled={loadingMore}
                className="w-full rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8] disabled:opacity-50">
                {loadingMore ? "Loading…" : `Load more (${total - reports.length} remaining)`}
              </button>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
