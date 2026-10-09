"use client";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAppContext } from "../context/AppContext";
import { Engagement, REPORT_STATUSES } from "../types";
import { safeMarkdownUrl } from "../lib/safeUrl";
import { Panel } from "./ui";
import { buttonClass, errorText, Field, fieldClass, Pages, requestJson } from "./workflowUi";

type Content = { title: string; executive_summary: string; methodology: string; limitations: string; remediation_priorities: string; finding_ids: string[] | null; evidence_ids: string[] };
type Deliverable = { id: string; title: string; latest_revision: number };
type Revision = { id: string; deliverable_id: string; revision: number; status: string; content_hash: string; markdown: string; snapshot: { editorial: Content }; created_at: string };
type Choice = { id: string; title: string; sensitivity?: string };
const empty = (): Content => ({ title: "Engagement assessment", executive_summary: "", methodology: "", limitations: "", remediation_priorities: "", finding_ids: null, evidence_ids: [] });
const labels = { executive_summary: "Executive summary", methodology: "Methodology", limitations: "Limitations", remediation_priorities: "Remediation priorities" } as const;

function Selection({ base, kind, selected, change }: { base: string; kind: "findings" | "evidence"; selected: string[]; change: (ids: string[]) => void }) {
  const { authFetch } = useAppContext();
  const [rows, setRows] = useState<Choice[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    void requestJson<Record<string, Choice[]> & { total: number }>(authFetch, `${base}/${kind}?limit=50&offset=${offset}`, { signal: c.signal }).then(d => { setRows(d[kind] ?? []); setTotal(d.total ?? 0); }).catch(e => { if (!c.signal.aborted) setError(errorText(e)); });
    return () => c.abort();
  }, [authFetch, base, kind, offset]);
  return <div className="space-y-2 text-xs text-[#94a3b8]">
    <p>Selected {kind}: {selected.length}</p>{error && <p role="alert">{error}</p>}
    {rows.map(row => <label key={row.id} className="flex gap-2"><input type="checkbox" checked={selected.includes(row.id)} onChange={e => change(e.target.checked ? [...selected, row.id] : selected.filter(id => id !== row.id))} />{row.title || row.id}{row.sensitivity && ` · ${row.sensitivity}`}</label>)}
    <Pages offset={offset} count={rows.length} total={total} change={setOffset} />
  </div>;
}

export default function EngagementDeliverables({ engagement }: { engagement: Engagement }) {
  const { authFetch } = useAppContext();
  const base = `/engagements/${engagement.id}`;
  const path = `${base}/deliverables`;
  const readOnly = engagement.my_role === "viewer";
  const [reports, setReports] = useState<Deliverable[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Deliverable | null>(null);
  const [revision, setRevision] = useState<Revision | null>(null);
  const [versions, setVersions] = useState<Revision[]>([]);
  const [versionTotal, setVersionTotal] = useState(0);
  const [versionOffset, setVersionOffset] = useState(0);
  const [content, setContent] = useState<Content>(empty);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const c = new AbortController();
    void requestJson<{ deliverables?: Deliverable[]; total?: number }>(authFetch, `${path}?limit=50&offset=${offset}`, { signal: c.signal }).then(d => { setReports(d.deliverables ?? []); setTotal(d.total ?? 0); }).catch(e => { if (!c.signal.aborted) setError(errorText(e)); });
    return () => c.abort();
  }, [authFetch, path, offset, refresh]);
  useEffect(() => {
    if (!selected) return;
    const c = new AbortController();
    void requestJson<{ revisions: Revision[]; total: number }>(authFetch, `${path}/${selected.id}/revisions?limit=50&offset=${versionOffset}`, { signal: c.signal }).then(d => { setVersions(d.revisions ?? []); setVersionTotal(d.total ?? 0); }).catch(e => { if (!c.signal.aborted) setError(errorText(e)); });
    return () => c.abort();
  }, [authFetch, path, selected, versionOffset, refresh]);

  async function open(report: Deliverable, number: number) {
    setBusy(true); setError(""); setEditing(false);
    try {
      const row = await requestJson<Revision>(authFetch, `${path}/${report.id}/revisions/${number}`);
      if (selected?.id !== report.id) setVersionOffset(0);
      setSelected(report); setRevision(row); setContent(row.snapshot.editorial);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setError("");
    try {
      const row = await requestJson<Revision>(authFetch, selected ? `${path}/${selected.id}/revisions` : path, { method: "POST", body: JSON.stringify({ ...content, ...(selected ? { base_revision: selected.latest_revision } : {}) }) });
      setRevision(row); setSelected({ id: row.deliverable_id, title: content.title, latest_revision: row.revision }); setEditing(false); setVersionOffset(0); setOffset(0); setRefresh(n => n + 1);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  async function status(value: string) {
    if (!revision) return;
    setBusy(true); setError("");
    try { setRevision(await requestJson<Revision>(authFetch, `${path}/${revision.deliverable_id}/revisions/${revision.revision}`, { method: "PATCH", body: JSON.stringify({ status: value }) })); setRefresh(n => n + 1); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  function download() {
    if (!revision) return;
    const url = URL.createObjectURL(new Blob([revision.markdown], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = `engagement-report-${revision.deliverable_id}-v${revision.revision}.md`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function print() {
    if (!revision) return;
    const target = window.open("", "_blank", "popup");
    if (!target) { setError("Allow a print window to print or save this revision as PDF."); return; }
    target.opener = null;
    target.document.title = `${revision.snapshot.editorial.title} — revision ${revision.revision}`;
    const style = target.document.createElement("style");
    style.textContent = "body{font:12pt Georgia,serif;line-height:1.5;margin:2cm;color:#111}h1,h2,h3,h4{break-after:avoid}p{white-space:pre-wrap;overflow-wrap:anywhere}h2{border-bottom:1px solid #aaa;padding-bottom:6px}@page{margin:1.5cm}";
    target.document.head.append(style);
    for (const block of revision.markdown.trim().split(/\n\n+/)) {
      const heading = /^(#{1,4}) (.*)$/.exec(block);
      const node = target.document.createElement(heading ? `h${heading[1].length}` : "p");
      node.textContent = heading ? heading[2] : block; target.document.body.append(node);
    }
    target.focus(); target.print();
  }

  return <Panel title="Engagement client reports">
    <div className="space-y-4">
      <p className="text-sm text-[#94a3b8]">Create a versioned client deliverable from the engagement record. Each revision freezes its scope, findings, selected evidence, and retest history.</p>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      <div className="flex flex-wrap gap-2">{reports.map(report => <button key={report.id} disabled={busy} className={buttonClass} onClick={() => void open(report, report.latest_revision)}>{report.title} · v{report.latest_revision}</button>)}
        {!readOnly && <button disabled={busy} className={buttonClass} onClick={() => { setSelected(null); setRevision(null); setContent(empty()); setEditing(true); setError(""); }}>New engagement report</button>}</div>
      {total > 50 && <Pages offset={offset} count={reports.length} total={total} change={setOffset} busy={busy} />}
      {editing && !readOnly && <form className="space-y-4" onSubmit={e => { e.preventDefault(); void save(); }}>
        <fieldset className="space-y-4" disabled={busy}>
          <Field label="Engagement report title"><input required maxLength={200} className={fieldClass} value={content.title} onChange={e => setContent({ ...content, title: e.target.value })} /></Field>
          <div className="grid gap-4 lg:grid-cols-2">{(Object.keys(labels) as (keyof typeof labels)[]).map(key => <Field key={key} label={labels[key]}><textarea rows={5} maxLength={20000} className={fieldClass} value={content[key]} onChange={e => setContent({ ...content, [key]: e.target.value })} /></Field>)}</div>
          <label className="flex gap-2 text-sm text-[#94a3b8]"><input type="checkbox" checked={content.finding_ids === null} onChange={e => setContent({ ...content, finding_ids: e.target.checked ? null : [] })} />Include all engagement findings at save time</label>
          {content.finding_ids !== null && <Selection base={base} kind="findings" selected={content.finding_ids} change={ids => setContent({ ...content, finding_ids: ids })} />}
          <details><summary className="cursor-pointer text-sm text-[#89b4fa]">Select evidence ({content.evidence_ids.length})</summary><p className="my-2 text-xs text-[#94a3b8]">Selected evidence is copied into the report revision and remains there even if the source evidence is later deleted.</p><Selection base={base} kind="evidence" selected={content.evidence_ids} change={ids => setContent({ ...content, evidence_ids: ids })} /></details>
          <div className="flex gap-2"><button type="submit" className={buttonClass} disabled={busy || !content.title.trim()}>{busy ? "Saving…" : selected ? "Save new revision" : "Create revision 1"}</button><button type="button" className={buttonClass} onClick={() => setEditing(false)}>Cancel</button></div>
        </fieldset>
      </form>}
      {revision && !editing && <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2"><span className="text-sm text-[#e2e8f0]">Revision {revision.revision} · {new Date(revision.created_at).toLocaleString()}</span>
          <select aria-label="Report revision status" className={fieldClass + " max-w-48"} disabled={busy || readOnly} value={revision.status} onChange={e => void status(e.target.value)}>{REPORT_STATUSES.map(s => <option key={s} value={s}>{s.replaceAll("_", " ")}</option>)}</select>
          <button className={buttonClass} onClick={download}>Download Markdown</button><button className={buttonClass} onClick={print}>Print / save PDF</button>
          {!readOnly && <button className={buttonClass} disabled={busy || revision.revision !== selected?.latest_revision} onClick={() => setEditing(true)}>Draft next revision</button>}
        </div>
        <p className="break-all font-mono text-[10px] text-[#94a3b8]">SHA-256 {revision.content_hash}</p>
        <details><summary className="cursor-pointer text-xs text-[#89b4fa]">Revision history</summary><div className="my-3 flex flex-wrap gap-2">{versions.map(v => <button key={v.id} className={buttonClass} disabled={busy} onClick={() => selected && void open(selected, v.revision)}>v{v.revision} · {v.status}</button>)}</div><Pages offset={versionOffset} count={versions.length} total={versionTotal} change={setVersionOffset} busy={busy} /></details>
        <div className="max-h-[700px] space-y-3 overflow-auto rounded border border-[#393939] p-5 text-sm leading-relaxed text-[#cbd5e1] [&_h1]:text-2xl [&_h2]:mt-6 [&_h2]:text-xl [&_h3]:mt-4 [&_h3]:text-lg [&_pre]:whitespace-pre-wrap [&_pre]:break-all [&_ul]:list-disc [&_ul]:pl-5">
          <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={safeMarkdownUrl} components={{ img: ({ alt }) => <span>{alt ? `[Image: ${alt}]` : "[Image omitted]"}</span> }}>{revision.markdown}</ReactMarkdown>
        </div>
      </div>}
    </div>
  </Panel>;
}
