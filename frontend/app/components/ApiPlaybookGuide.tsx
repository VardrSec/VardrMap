"use client";
import { useEffect, useState } from "react";
import { useAppContext } from "../context/AppContext";
import { buttonClass, errorText, Field, fieldClass, requestJson } from "./workflowUi";

type Summary = { id: string; title: string; version: string; use_when: string };
type Playbook = Summary & { prerequisites: string[]; expected_artifacts: string; steps: string[]; common_traps: string; manual_remainder: string };

export default function ApiPlaybookGuide({ engagementId }: { engagementId: string }) {
  const { authFetch } = useAppContext();
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<Summary[]>([]);
  const [selected, setSelected] = useState("");
  const [book, setBook] = useState<Playbook | null>(null);
  const [error, setError] = useState("");
  const base = `/engagements/${engagementId}/playbooks`;
  useEffect(() => {
    if (!open) return;
    const c = new AbortController();
    void requestJson<{ playbooks: Summary[] }>(authFetch, base, { signal: c.signal }).then(data => {
      if (!Array.isArray(data.playbooks)) throw new Error("Playbook catalog was not recognized.");
      if (!c.signal.aborted) { setCatalog(data.playbooks); setSelected(data.playbooks[0]?.id ?? ""); }
    }).catch(e => { if (!c.signal.aborted) setError(errorText(e)); });
    return () => c.abort();
  }, [authFetch, base, open]);
  useEffect(() => {
    if (!open || !selected) return;
    const c = new AbortController();
    void requestJson<Playbook>(authFetch, `${base}/${encodeURIComponent(selected)}`, { signal: c.signal }).then(data => {
      if (!c.signal.aborted) { setBook(data); setError(""); }
    }).catch(e => { if (!c.signal.aborted) setError(errorText(e)); });
    return () => c.abort();
  }, [authFetch, base, open, selected]);
  return <div className="rounded-lg border border-[#2e2e2e] p-3">
    <button className={buttonClass} aria-expanded={open} onClick={() => { setOpen(!open); setBook(null); setSelected(""); setError(""); }}>{open ? "Hide API playbooks" : "Show API playbooks"}</button>
    {open && <div className="mt-3 space-y-3 text-sm text-[#cbd5e1]">
      <p>Guidance for planning and reviewing API tests. Reading a playbook records no testing progress.</p>
      {error && <p role="alert" className="text-red-400">{error}</p>}
      <Field label="API playbook"><select className={fieldClass} value={selected} onChange={e => { setSelected(e.target.value); setBook(null); }}><option value="">Choose a playbook</option>{catalog.map(p => <option key={p.id} value={p.id}>{p.id}: {p.title} · v{p.version}</option>)}</select></Field>
      {book && <>
        <p className="font-semibold">{book.id} · version {book.version}</p><p>{book.use_when}</p>
        <p className="font-semibold">Before testing</p><ul className="list-disc space-y-1 pl-5">{book.prerequisites.map((s, i) => <li key={i}>{s}</li>)}</ul>
        <p className="font-semibold">Expected artifacts</p><p>{book.expected_artifacts}</p>
        <ol className="list-decimal space-y-2 pl-5">{book.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
        <p className="font-semibold">Common traps</p><p>{book.common_traps}</p>
        <p className="font-semibold">Manual testing and review</p><p>{book.manual_remainder}</p>
      </>}
    </div>}
  </div>;
}
