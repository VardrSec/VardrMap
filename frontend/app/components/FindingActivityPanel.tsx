"use client";
import { useCallback, useEffect, useState } from "react";
import { useAppContext } from "../context/AppContext";
import { buttonClass, errorText, Field, fieldClass, Pages, requestJson } from "./workflowUi";

type Activity = { id: string; kind: string; outcome: string | null; notes: string; actor: string; created_at: string; snapshot: Record<string, unknown>; evidence: { id: string; title: string; content_hash: string }[] };
type Evidence = { id: string; title: string; body: string };

export default function FindingActivityPanel(props: { engagementId: string; findingId: string; readOnly: boolean }) {
  const [open, setOpen] = useState(false);
  return <details className="mt-4 border-t border-[#2e2e2e] pt-3" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer text-xs text-[#89b4fa]">Remediation &amp; retests</summary>
    {open && <Timeline {...props} />}
  </details>;
}

function Timeline({ engagementId, findingId, readOnly }: { engagementId: string; findingId: string; readOnly: boolean }) {
  const { authFetch } = useAppContext();
  const base = `/engagements/${engagementId}`;
  const path = `${base}/findings/${findingId}/activity`;
  const [entries, setEntries] = useState<Activity[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState("remediation");
  const [outcome, setOutcome] = useState("inconclusive");
  const [notes, setNotes] = useState("");
  const [evidenceBody, setEvidenceBody] = useState("");
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [evidenceOffset, setEvidenceOffset] = useState(0);
  const [evidenceTotal, setEvidenceTotal] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const load = useCallback(async (signal: AbortSignal) => {
    const data = await requestJson<{ activities?: Activity[]; total?: number }>(authFetch, `${path}?limit=50&offset=${offset}`, { signal });
    setEntries(data.activities ?? []); setTotal(data.total ?? 0);
  }, [authFetch, path, offset]);
  useEffect(() => { const c = new AbortController(); void load(c.signal).catch(e => { if (!c.signal.aborted) setError(errorText(e)); }); return () => c.abort(); }, [load, refresh]);
  useEffect(() => {
    const c = new AbortController();
    void requestJson<{ evidence?: Evidence[]; total?: number }>(authFetch, `${base}/evidence?finding_id=${findingId}&limit=50&offset=${evidenceOffset}`, { signal: c.signal }).then(d => { setEvidence(d.evidence ?? []); setEvidenceTotal(d.total ?? 0); }).catch(e => { if (!c.signal.aborted) setError(errorText(e)); });
    return () => c.abort();
  }, [authFetch, base, findingId, evidenceOffset, refresh]);

  async function save() {
    setBusy(true); setError("");
    try {
      let ids = selected;
      if (evidenceBody.trim()) {
        const e = await requestJson<Evidence>(authFetch, `${base}/evidence`, { method: "POST", body: JSON.stringify({ finding_id: findingId, title: `${kind === "retest" ? "Retest" : "Remediation"} evidence`, kind: "note", body: evidenceBody, source: "operator", sensitivity: "internal" }) });
        ids = [...ids, e.id]; setSelected(ids); setEvidenceBody("");
      }
      await requestJson(authFetch, path, { method: "POST", body: JSON.stringify({ kind, notes, outcome: kind === "retest" ? outcome : null, evidence_ids: ids }) });
      setNotes(""); setSelected([]); setOffset(0); setRefresh(n => n + 1);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }

  return <div className="mt-4 space-y-4">
    <p className="text-xs text-[#94a3b8]">Updates retain the original finding. A verified retest does not change its status automatically.</p>
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
    {!readOnly && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void save(); }}>
      <fieldset disabled={busy} className="space-y-3">
        <Field label="Update type"><select className={fieldClass} value={kind} onChange={e => setKind(e.target.value)}><option value="remediation">Remediation update</option><option value="retest">Retest attempt</option></select></Field>
        {kind === "retest" && <Field label="Verification outcome"><select className={fieldClass} value={outcome} onChange={e => setOutcome(e.target.value)}>{["inconclusive", "still_open", "partially_fixed", "verified_fixed"].map(v => <option key={v} value={v}>{v.replaceAll("_", " ")}</option>)}</select></Field>}
        <Field label="Update notes"><textarea required maxLength={10000} className={fieldClass} value={notes} onChange={e => setNotes(e.target.value)} /></Field>
        <Field label="New evidence (optional)"><textarea maxLength={200000} className={fieldClass} value={evidenceBody} onChange={e => setEvidenceBody(e.target.value)} placeholder="Retest observation or redacted response" /></Field>
        {evidence.length > 0 && <div className="space-y-2 text-xs text-[#94a3b8]"><p>Attach existing evidence ({selected.length} selected)</p>{evidence.map(e => <label key={e.id} className="flex gap-2"><input type="checkbox" checked={selected.includes(e.id)} onChange={event => setSelected(ids => event.target.checked ? [...ids, e.id] : ids.filter(id => id !== e.id))} />{e.title || e.id}</label>)}<Pages count={evidence.length} offset={evidenceOffset} total={evidenceTotal} change={setEvidenceOffset} busy={busy} /></div>}
        <button type="submit" disabled={busy || !notes.trim()} className={buttonClass}>{busy ? "Saving…" : "Save update"}</button>
      </fieldset>
    </form>}
    <ol className="space-y-3">{entries.map(entry => <li key={entry.id} className="rounded border border-[#393939] p-3 text-xs text-[#94a3b8]">
      <p className="font-semibold text-[#e2e8f0]">{entry.kind} {entry.outcome?.replaceAll("_", " ")}</p><p>{new Date(entry.created_at).toLocaleString()} · {entry.actor}</p>
      <p className="mt-2 whitespace-pre-wrap">{entry.notes}</p>
      {entry.evidence.map(e => <p key={e.id} className="mt-2 break-all">Evidence: {e.title || e.id} · SHA-256 {e.content_hash}</p>)}
      <details className="mt-2"><summary className="cursor-pointer">Finding at this point</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap">{JSON.stringify(entry.snapshot, null, 2)}</pre></details>
    </li>)}</ol>
    <Pages count={entries.length} offset={offset} total={total} change={setOffset} busy={busy} />
  </div>;
}
