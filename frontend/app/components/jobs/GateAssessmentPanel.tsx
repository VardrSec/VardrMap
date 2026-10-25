"use client";
import { useEffect, useState } from "react";
import type { ScanJobUI } from "../../types";
import { useAppContext } from "../../context/AppContext";
import { Panel } from "../ui";
import { buttonClass, errorText, Field, fieldClass, Pages, requestJson } from "../workflowUi";

type Evidence = { id: string; title: string; body: string; content_hash: string; finding_id: string; job_id: string | null; case_id: string | null; case_ref: string | null; identity_id: string | null; expected_decision: string | null; observed_outcome: string | null };
type Finding = { id: string; title: string };

export default function GateAssessmentPanel({ engagementId, job }: { engagementId: string; job: ScanJobUI }) {
  const { authFetch, selectedEngagement } = useAppContext();
  const readOnly = selectedEngagement?.my_role === "viewer";
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [findingTotal, setFindingTotal] = useState(0);
  const [findingOffset, setFindingOffset] = useState(0);
  const [findingId, setFindingId] = useState("");
  const [linking, setLinking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const base = `/engagements/${engagementId}`;
  useEffect(() => {
    const c = new AbortController();
    void requestJson<{ evidence: Evidence[]; total: number }>(authFetch, `${base}/evidence?job_id=${encodeURIComponent(job.id)}&limit=50&offset=${offset}`, { signal: c.signal }).then(data => {
      if (!Array.isArray(data.evidence) || typeof data.total !== "number") throw new Error("Evidence response was not recognized.");
      if (!c.signal.aborted) { setEvidence(data.evidence); setTotal(data.total); setLoaded(true); }
    }).catch(e => { if (!c.signal.aborted) setError(errorText(e)); });
    return () => c.abort();
  }, [authFetch, base, job.id, job.assessment, offset]);
  useEffect(() => {
    if (!linking || readOnly) return;
    const c = new AbortController();
    void requestJson<{ findings: Finding[]; total: number }>(authFetch, `${base}/findings?limit=50&offset=${findingOffset}`, { signal: c.signal }).then(data => {
      if (!Array.isArray(data.findings) || typeof data.total !== "number") throw new Error("Finding response was not recognized.");
      if (!c.signal.aborted) { setFindings(data.findings); setFindingTotal(data.total); }
    }).catch(e => { if (!c.signal.aborted) setError(errorText(e)); });
    return () => c.abort();
  }, [authFetch, base, findingOffset, linking, readOnly]);
  async function link(id: string) {
    setBusy(true); setError("");
    try {
      const updated = await requestJson<Evidence>(authFetch, `${base}/evidence/${id}/link`, { method: "POST", body: JSON.stringify({ finding_id: findingId }) });
      setEvidence(items => items.map(e => e.id === id ? updated : e));
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const a = job.assessment;
  return <Panel title="API assessment & execution evidence"><div className="space-y-3 text-sm text-[#cbd5e1]">
    <p>Job: {job.id}</p>
    <p>Assessment: {a?.status ?? "not recorded"}. Job completion alone does not establish authorization or a clean result.</p>
    {a && <><p>{a.evaluated} evaluated · {a.inconclusive} inconclusive · {a.missing} missing · {a.skipped} skipped · {a.unexpected} unexpected executions</p><p>Legitimate baseline: {a.baseline_valid ? "reported working" : "not established"}. Scanner findings remain candidates.</p>
      <p>Case: {a.case_ref ?? "unknown"} · {a.case_id ?? "unknown"}</p><p className="break-all text-xs">Case SHA-256: {a.case_hash ?? "not recorded"}</p>
      <p>Result matches claimed case snapshot: {a.case_snapshot_verified ? "reported hash matches" : "not confirmed"}.</p>
      <p>Identity preflight: {a.preflight?.status.replaceAll("_", " ") ?? "not recorded"}. A session check does not establish authorization to the resource under test.</p>
      {a.preflight?.identities.map(i => <p key={"preflight-" + i.identity_id}>Session {i.identity_id}: {i.status} ({i.reason.replaceAll("_", " ")}){i.status_code !== null ? ` · HTTP ${i.status_code}` : ""}</p>)}
      {a.identities.map(i => <div key={i.identity_id} className="rounded border border-[#2e2e2e] p-3">
        <p>{i.identity_id}: expected {i.expected_decision} · raw HTTP outcome {i.observed_outcome}</p>
        <p>Scanner assessment: {i.reported_decision ?? "not recorded"} · completeness {i.state} ({i.reason.replaceAll("_", " ")})</p>
        <p>Credential check: {(i.credential_status ?? "not recorded").replaceAll("_", " ")} · write readback: {(i.write_verification ?? "not recorded").replaceAll("_", " ")}</p>
        <p>Evidence source: {i.source ?? "not recorded"}{i.matched_assertions?.length ? ` · assertion indices ${i.matched_assertions.join(", ")}` : ""}</p>
        {i.verification && <p>Reader {i.verification.reader_identity_id}: {i.verification.reader_credential_status.replaceAll("_", " ")} · before HTTP {i.verification.before_statuses.join(", ")} · after HTTP {i.verification.after_status || "unavailable"} · {i.verification.strategy} / {i.verification.environment}</p>}
      </div>)}
      <p>Credential checks describe a point in time. Missing checks and missing readback are unknown; scanner conclusions still need operator confirmation.</p>
    </>}
    {error && <p role="alert" className="text-red-400">{error}</p>}
    {!readOnly && <button className={buttonClass} onClick={() => setLinking(!linking)}>{linking ? "Hide finding selection" : "Link evidence to a finding"}</button>}
    {linking && !readOnly && <><Field label="Finding for selected evidence"><select className={fieldClass} value={findingId} onChange={e => setFindingId(e.target.value)}><option value="">Choose a finding</option>{findings.map(f => <option key={f.id} value={f.id}>{f.title}</option>)}</select></Field><Pages offset={findingOffset} count={findings.length} total={findingTotal} busy={busy} change={n => { setFindingId(""); setFindingOffset(n); }} /></>}
    {evidence.map(e => <div key={e.id} className="rounded border border-[#2e2e2e] p-3">
      <p className="font-semibold">{e.title}</p><p>Case: {e.case_ref ?? "unknown"} · Identity: {e.identity_id ?? "unknown"}</p><p>Expected {e.expected_decision ?? "unknown"} · observed {e.observed_outcome ?? "unknown"}</p>
      <p className="break-all text-xs">Evidence {e.id} · Job {e.job_id ?? "unknown"} · Case {e.case_id ?? "unknown"}</p><p className="break-all text-xs">SHA-256 {e.content_hash}</p>
      <details><summary className="cursor-pointer">Redacted execution record</summary><pre className="overflow-auto whitespace-pre-wrap break-all text-xs">{e.body}</pre></details>
      {e.finding_id ? <p>Linked finding: {e.finding_id}</p> : linking && !readOnly && <button className={buttonClass + " mt-2"} disabled={busy || !findingId} onClick={() => void link(e.id)}>Link this evidence</button>}
    </div>)}
    {!error && loaded && total === 0 && <p>No execution evidence recorded for this job.</p>}{!loaded && !error && <p>Loading execution evidence…</p>}{loaded && <Pages offset={offset} count={evidence.length} total={total} busy={busy} change={setOffset} />}
  </div></Panel>;
}
