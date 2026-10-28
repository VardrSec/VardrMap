"use client";
import { useState } from "react";
import ApiPlaybookGuide from "./ApiPlaybookGuide";
import { useAppContext } from "../context/AppContext";
import { Panel } from "./ui";
import { buttonClass, errorText, Field, fieldClass, Pages, requestJson } from "./workflowUi";

const BOUNDARY_LABEL: Record<string, string> = {
  cross_tenant: "different-tenant", same_tenant_peer: "same-tenant peer", higher_privilege: "higher-role", anonymous: "no-credentials",
};

export default function AuthorizationCaseBuilder({ engagementId, endpointIds, identityIds = [], boundary = "" }: { engagementId: string; endpointIds: string[]; identityIds?: string[]; boundary?: string }) {
  const { authFetch, selectedEngagement } = useAppContext();
  const [source, setSource] = useState("operations");
  const [document, setDocument] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [drafts, setDrafts] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [offset, setOffset] = useState(0);
  const [count, setCount] = useState(0);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [context, setContext] = useState<{ boundary: string; missing_context: string[]; conflicts: { identity_id: string; attribute: string; values: string[] }[] } | null>(null);
  const readOnly = selectedEngagement?.my_role === "viewer";
  const path = `/engagements/${engagementId}/test-cases`;

  async function preview(nextOffset = 0) {
    setBusy(true); setError(""); setMessage(""); setReviewed(false);
    try {
      const input = source === "operations" ? { endpoint_ids: endpointIds, ...(boundary ? { boundary } : identityIds.length ? { identity_ids: identityIds } : {}) } : { openapi: JSON.parse(document) };
      const data = await requestJson<{ drafts: unknown[]; total: number; boundary_context?: { boundary: string; missing_context: string[]; conflicts: { identity_id: string; attribute: string; values: string[] }[] } | null }>(authFetch, path + "/preview", { method: "POST", body: JSON.stringify({ ...input, base_url: baseUrl, limit: 50, offset: nextOffset }) });
      setContext(data.boundary_context ?? null);
      setDrafts(JSON.stringify(data.drafts, null, 2)); setTotal(data.total); setCount(data.drafts.length); setOffset(nextOffset);
      setMessage("Drafts are ready for review. No cases have been stored or queued.");
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setError(""); setMessage("");
    try {
      const cases: unknown = JSON.parse(drafts);
      if (!Array.isArray(cases)) throw new Error("Draft cases must be a JSON array.");
      const data = await requestJson<{ test_cases: unknown[] }>(authFetch, path + "/reviewed", { method: "POST", body: JSON.stringify({ reviewed, cases }) });
      setDrafts(""); setReviewed(false); setMessage(`${data.test_cases.length} reviewed cases saved. Select them in the job composer to run VardrGate.`);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <Panel title="Draft authorization tests">
    <div className="space-y-4">
      <ApiPlaybookGuide key={engagementId} engagementId={engagementId} />
      <p className="text-sm text-[#94a3b8]">Choose observed Burp operations below or load an OpenAPI 3.x JSON document. Review concrete URLs, request bodies, identity references, and expected access before saving.</p>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}{message && <p role="status" className="text-sm text-[#a6e3a1]">{message}</p>}
      <fieldset className="space-y-3" disabled={busy}>
        <Field label="Draft source"><select className={fieldClass} value={source} onChange={e => { setSource(e.target.value); setDrafts(""); setReviewed(false); }}><option value="operations">Selected observed operations ({endpointIds.length}){boundary ? ` · ${BOUNDARY_LABEL[boundary] ?? boundary} question` : identityIds.length ? ` · ${identityIds.length} engagement identities` : ""}</option><option value="openapi">OpenAPI JSON</option></select></Field>
        {source === "openapi" && <><Field label="OpenAPI JSON file"><input type="file" accept=".json,application/json" className={fieldClass} onChange={async e => {
          const file = e.target.files?.[0]; if (!file) return;
          if (file.size > 2 * 1024 * 1024) { setError("OpenAPI file exceeds 2 MiB."); return; }
          try { setDocument(await file.text()); setDrafts(""); setReviewed(false); } catch { setError("Could not read the OpenAPI file."); }
        }} /></Field><Field label="OpenAPI document"><textarea rows={6} className={fieldClass + " font-mono"} value={document} onChange={e => setDocument(e.target.value)} placeholder='{"openapi":"3.1.0","servers":[{"url":"https://api.example.test"}],"paths":{}}' /></Field></>}
        <Field label="Base URL override (optional)"><input type="url" className={fieldClass} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.example.test/v1" /></Field>
        <button className={buttonClass} disabled={busy || (source === "operations" ? endpointIds.length === 0 : !document.trim())} onClick={() => void preview()}>Generate draft cases</button>
      </fieldset>
      {drafts && <div className="space-y-3">
        {context && <div role="note" className="rounded border border-[#3f2f12] bg-[#1a1408] p-3 text-xs text-[#fbbf24]">
          <div className="font-semibold">Not ready to run: this {BOUNDARY_LABEL[context.boundary] ?? context.boundary} draft is a question, not a test.</div>
          <p className="mt-1">Every expected access is <code>skip</code> until you decide it. Nothing has been saved or queued.</p>
          {context.missing_context.length > 0 && <ul className="mt-1 list-disc pl-4">{context.missing_context.map((line) => <li key={line}>{line}</li>)}</ul>}
          {context.conflicts.length > 0 && <p className="mt-1 text-[#f87171]">Contradictory declarations were not used: {context.conflicts.map((c) => `${c.identity_id} ${c.attribute} (${c.values.join(" vs ")})`).join("; ")}.</p>}
        </div>}
        <p className="text-xs text-[#94a3b8]">Edit the generated JSON. Identity credentials use <code>value_env</code> or <code>value_keychain</code>, never token values. Replace path variables, set one allow/deny/skip decision per identity, and review mutating operations. Remove unwanted cases from this page before saving.</p>
        <Field label="Draft cases JSON"><textarea rows={20} spellCheck={false} disabled={busy} className={fieldClass + " font-mono"} value={drafts} onChange={e => { setDrafts(e.target.value); setReviewed(false); }} /></Field>
        <details className="text-xs text-[#94a3b8]"><summary className="cursor-pointer">Check authenticated identities before testing</summary><p>Add a preflight to each authenticated identity using a known-good GET endpoint on the API origin. Match public subject, role or tenant metadata. Any failed check stops the case before authorization requests. Anonymous identities have no preflight. Secrets remain local credential references.</p><pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify({ preflight: { url: "https://api.example.test/session", expected_status: 200, json_fields: { "user.id": "reviewed-user-id", "user.tenant_id": "reviewed-tenant-id" } } }, null, 2)}</pre></details>
        <p className="text-xs text-[#94a3b8]">Changing pages replaces this unsaved page. Save or copy your edits first.</p>
        <Pages offset={offset} count={count} total={total} busy={busy} change={n => void preview(n)} />
        {!readOnly && <><label className="flex gap-2 text-sm text-[#cbd5e1]"><input type="checkbox" disabled={busy} checked={reviewed} onChange={e => setReviewed(e.target.checked)} />I reviewed the request targets, identity references, and expected access decisions.</label><button className={buttonClass} disabled={busy || !reviewed} onClick={() => void save()}>{busy ? "Working…" : "Save reviewed cases"}</button></>}
      </div>}
    </div>
  </Panel>;
}
