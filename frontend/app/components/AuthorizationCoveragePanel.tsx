"use client";

import { useEffect, useRef, useState } from "react";
import { useAppContext } from "../context/AppContext";
import type { AuthorizationCoverage, AuthorizationObservation, CoverageEvidenceRef, CoverageOperation, CoverageState } from "../types";
import { Panel } from "./ui";
import WorkflowReviewSummary from "./WorkflowReviewSummary";

/**
 * Where authorization testing is incomplete, computed by the backend from stored
 * inventory, reviewed cases, executed jobs and their evidence. The backend
 * checks each run against the proof required by its frozen case.
 */

const PAGE_SIZE = 500;
const STATE_LABEL: Record<CoverageState, string> = {
  violation_candidate: "Violation candidate",
  inconclusive: "Inconclusive",
  partial: "Partial",
  conclusive: "Conclusive",
  reviewed_not_executed: "Reviewed, not executed",
  stale: "Case changed since last run",
  untested: "No reviewed test",
};
const STATE_COLOR: Record<CoverageState, string> = {
  violation_candidate: "#f87171",
  inconclusive: "#f59e0b",
  partial: "#fbbf24",
  conclusive: "#4ade80",
  reviewed_not_executed: "#89b4fa",
  stale: "#c084fc",
  untested: "#6b7280",
};
const STATE_ORDER: CoverageState[] = [
  "violation_candidate", "inconclusive", "partial", "conclusive", "reviewed_not_executed", "stale", "untested",
];
const IDENTITY_LABEL: Record<string, string> = {
  evaluated: "evaluated",
  inconclusive: "inconclusive",
  mixed: "evaluated in some cases only",
  missing: "no result reported",
  skipped: "no expectation",
  reviewed_not_run: "reviewed, not run",
  not_reviewed: "not reviewed",
};
const IDENTITY_COLOR: Record<string, string> = {
  evaluated: "#4ade80", inconclusive: "#f59e0b", mixed: "#fbbf24", missing: "#f59e0b",
  skipped: "#6b7280", reviewed_not_run: "#89b4fa", not_reviewed: "#52525b",
};

const HISTORY_REASON: Record<string, string> = {
  case_modified: "the case was edited after this run",
  case_deleted: "the case was deleted",
  snapshot_unverified: "the case snapshot was not verified",
};

function operationCount(data: AuthorizationCoverage | null, state: CoverageState | "") {
  return data?.filtered_total ?? (state ? data?.summary?.[state] : data?.summary?.total);
}

function StateBadge({ state }: { state: CoverageState }) {
  return <span className="rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
    style={{ color: STATE_COLOR[state], background: `${STATE_COLOR[state]}1f` }}>{STATE_LABEL[state]}</span>;
}

export function ObservationDetails({ result }: { result: AuthorizationObservation }) {
  return <>
    <div>Expected {result.expected} · Raw HTTP outcome {result.observed}</div>
    <div>Reported decision {result.reported_decision ?? "not recorded"}</div>
    {result.source && <div>Decision source {result.source}</div>}
    {result.write_verification && <div>Write verification {result.write_verification}</div>}
  </>;
}

/** The retained, redacted record behind a candidate, loaded only when asked for. */
function EvidenceRecord({ engagementId, reference }: { engagementId: string; reference: CoverageEvidenceRef }) {
  const { authFetch } = useAppContext();
  const [record, setRecord] = useState<{ body: string; content_hash: string } | "unavailable" | "different-id" | null>(null);
  async function open() {
    try {
      const res = await authFetch(`/engagements/${engagementId}/evidence/${encodeURIComponent(reference.evidence_id)}`);
      if (!res.ok) throw new Error();
      const row = await res.json();
      if (!row?.id || typeof row.body !== "string" || typeof row.content_hash !== "string" || !row.content_hash) throw new Error();
      setRecord(row.id === reference.evidence_id ? { body: row.body, content_hash: row.content_hash } : "different-id");
    } catch { setRecord("unavailable"); }
  }
  return <div className="mt-1 rounded border border-[#2e2e2e] bg-[#111] p-2 text-[10px] text-[#94a3b8]">
    <div className="font-mono text-[#f1f5f9]">{reference.identity_id ?? "unknown identity"} · job {reference.job_id.slice(0, 8)}</div>
    <ObservationDetails result={reference} />
    {record === null && <button type="button" onClick={() => void open()} className="text-[#89b4fa] hover:underline">View redacted record</button>}
    {record === "unavailable" && <div className="mt-1 text-[#f87171]">The cited evidence is unavailable.</div>}
    {record === "different-id" && <div className="mt-1 text-[#f87171]">The returned evidence ID differs from the coverage reference.</div>}
    {record && typeof record === "object" && (record.content_hash === reference.content_hash ? <>
      <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-mono">{record.body}</pre>
      <div className="mt-1 font-mono text-muted">sha256 {record.content_hash} (matches)</div>
    </> : <div className="mt-1 text-[#f87171]">sha256 {record.content_hash} (differs from the coverage reference)</div>)}
  </div>;
}

export default function AuthorizationCoveragePanel({ engagementId, onDraft }: { engagementId: string; onDraft?: (endpointId: string, identityIds: string[]) => void }) {
  const { authFetch, setMessage } = useAppContext();
  const [state, setState] = useState<CoverageState | "">("");
  // Loading is derived from which request the stored result answers, so the effect
  // never sets state synchronously (only after the response arrives).
  const [byPriority, setByPriority] = useState(false);
  const [offset, setOffset] = useState(0);
  const pageStatus = useRef<HTMLParagraphElement>(null);
  const requestKey = `${engagementId}|${state}|${byPriority}|${offset}`;
  const [result, setResult] = useState<{ key: string; data: AuthorizationCoverage | null }>({ key: "", data: null });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
        if (state) params.set("state", state);
        if (byPriority) params.set("sort", "priority");
        if (offset) params.set("offset", String(offset));
        const res = await authFetch(`/engagements/${engagementId}/api/coverage?${params}`);
        if (!res.ok) throw new Error();
        const body = (await res.json()) as AuthorizationCoverage;
        if (cancelled) return;
        const total = operationCount(body, state);
        if (offset > 0 && total !== undefined && offset >= total) {
          // Operations can disappear between page requests. Fetch the last remaining page.
          setOffset(Math.max(0, Math.ceil(total / PAGE_SIZE) - 1) * PAGE_SIZE);
          return;
        }
        setResult({ key: requestKey, data: body });
      } catch {
        if (!cancelled) {
          setMessage("Failed to load authorization coverage.");
          setResult({ key: requestKey, data: null });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch, byPriority, engagementId, offset, requestKey, setMessage, state]);

  const loading = result.key !== requestKey;
  const data = result.data;

  const operations: CoverageOperation[] = data?.operations ?? [];
  const summary = data?.summary;
  const unmatched = data?.unmatched_cases ?? [];
  const unattributed = data?.unattributed_assessments ?? [];
  const filteredTotal = operationCount(data, state) ?? 0;
  const pageFailed = !summary && offset > 0;
  if (!loading && !pageFailed && (!summary || (!summary.total && !unmatched.length && !unattributed.length))) return null;

  function goToPage(nextOffset: number) {
    pageStatus.current?.focus();
    setOffset(nextOffset);
  }

  let statusText = summary?.total ? "No operations in this state." : "No captured operations yet.";
  if (loading) statusText = "Computing coverage…";
  else if (pageFailed) statusText = "This page of operations could not be loaded.";
  else if (operations.length) {
    statusText = `Showing ${offset + 1}–${offset + operations.length} of ${filteredTotal} operation${filteredTotal === 1 ? "" : "s"}`;
  }

  return <Panel title="Authorization coverage">
    <p className="mb-4 text-xs text-muted">
      Which observed operations have a reviewed authorization test, whether it ran, and for which identities.
      <strong className="text-[#94a3b8]"> Conclusive describes reported outcomes with a working baseline; it does not mean the operation is secure.</strong>{" "}
      Identities listed as <em>not reviewed</em> exist elsewhere in this engagement but not in a test for that operation.
    </p>
    {!!summary?.total && <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-7">
      {STATE_ORDER.map((key) => <button key={key} type="button" aria-pressed={state === key}
        onClick={() => { setState(state === key ? "" : key); setOffset(0); }}
        className="rounded-lg border bg-[#171717] p-3 text-left transition hover:border-[#3a3a3a]"
        style={{ borderColor: state === key ? STATE_COLOR[key] : "#2e2e2e" }}>
        <div className="font-mono text-xl" style={{ color: STATE_COLOR[key] }}>{summary[key]}</div>
        <div className="mt-1 text-[10px] uppercase tracking-widest text-muted">{STATE_LABEL[key]}</div>
      </button>)}
    </div>}
    {!!summary?.total && <label className="mb-3 flex items-center gap-2 text-xs text-[#94a3b8]">
      <input type="checkbox" checked={byPriority} onChange={(e) => { setByPriority(e.target.checked); setOffset(0); }} />
      Look here first: least-tested states first, then operations with more reasons to look.
    </label>}
    <p ref={pageStatus} role="status" tabIndex={-1} className="my-3 text-xs text-muted">{statusText}</p>
    {!loading && operations.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left text-xs">
      <thead><tr className="border-b border-[#2e2e2e]">{["Operation", "State", "Candidates", "Identities", ""].map((h) =>
        <th key={h} className="pb-2 pr-4 font-semibold uppercase tracking-widest text-muted">{h}</th>)}</tr></thead>
      <tbody>{operations.map((op) => <tr key={op.endpoint_id} className="border-b border-[#1e1e1e] align-top">
        <td className="py-2.5 pr-4"><div className="font-mono text-[#f1f5f9]">{op.method} {op.path_template}</div>
          <div className="mt-0.5 text-[10px] text-muted">{op.host}</div>
          {(op.historical_assessments ?? []).length > 0 && <details className="mt-1 text-[10px] text-[#a1a1aa]">
            <summary className="cursor-pointer text-[#c084fc]">{op.historical_assessments.length} earlier assessment{op.historical_assessments.length === 1 ? "" : "s"} not counted as current coverage</summary>
            <ul className="mt-1 space-y-0.5">{op.historical_assessments.map((item) => <li key={item.job_id}>
              <span className="font-mono">{item.job_id.slice(0, 8)}</span> · {item.assessment_status ?? "no status"} · {HISTORY_REASON[item.reason] ?? item.reason}
              {item.case_name ? ` (${item.case_name})` : ""}{item.candidates.open + item.candidates.promoted > 0 ? ` · ${item.candidates.open} open candidate${item.candidates.open === 1 ? "" : "s"} still unresolved` : ""}</li>)}</ul>
          </details>}
          {(op.priority_reasons ?? []).length > 0 && <ul className="mt-1 space-y-0.5 text-[10px] text-[#a1a1aa]">
            {op.priority_reasons.map((reason) => <li key={reason.code}>{reason.detail}</li>)}</ul>}</td>
        <td className="py-2.5 pr-4"><StateBadge state={op.state} />
          {op.cases.length > 0 && <div className="mt-1 text-[10px] text-muted">{op.cases.length} reviewed case{op.cases.length === 1 ? "" : "s"}</div>}
          {op.cases.map(item => item.workflow_review ? <WorkflowReviewSummary key={item.case_id} review={item.workflow_review} label={`${item.name}: workflow prerequisites`} /> : null)}</td>
        <td className="py-2.5 pr-4 font-mono text-[#94a3b8]">{op.candidates.open + op.candidates.promoted > 0
          ? `${op.candidates.open} open · ${op.candidates.promoted} promoted · ${op.candidates.backing_evidence} with evidence` : "—"}
          {(op.candidate_evidence ?? []).map((reference) => <EvidenceRecord key={reference.evidence_id} engagementId={engagementId} reference={reference} />)}</td>
        <td className="py-2.5"><div className="flex flex-wrap gap-1.5">{op.identity_coverage.map((row) =>
          <span key={row.identity_id} title={row.reason ? `${IDENTITY_LABEL[row.state] ?? row.state}: ${row.reason.replace(/_/g, " ")}` : IDENTITY_LABEL[row.state] ?? row.state}
            className="rounded border px-1.5 py-0.5 font-mono text-[10px]"
            style={{ color: IDENTITY_COLOR[row.state] ?? "#94a3b8", borderColor: `${IDENTITY_COLOR[row.state] ?? "#94a3b8"}55` }}>
            {row.identity_id} · {IDENTITY_LABEL[row.state] ?? row.state}
          </span>)}{op.identity_coverage.length === 0 && <span className="text-muted">no identities declared in this engagement</span>}</div>
          {op.cases.filter(item => item.executed).map(item => <details key={item.case_id} className="mt-1 text-[10px] text-[#94a3b8]">
            <summary className="cursor-pointer">{item.name} · assessment details</summary>
            <div>Legitimate baseline {item.baseline_valid == null ? "not recorded" : item.baseline_valid ? "valid" : "not established"}</div>
            <ul>{Object.entries(item.identity_results ?? {}).map(([id, result]) => <li key={id} className="mt-1">
              <div className="font-mono text-[#f1f5f9]">{id} · {result.state}</div>
              {result.reason === "semantic_assessment_missing" && <div>Required semantic proof is missing.</div>}
              <ObservationDetails result={result} />
            </li>)}</ul>
          </details>)}</td>
        <td className="py-2.5 pl-3 text-right">{onDraft && op.identity_coverage.some((row) => row.state !== "evaluated") &&
          <button type="button" onClick={() => onDraft(op.endpoint_id, op.identity_coverage.map((row) => row.identity_id))}
            aria-label={`Draft a test for ${op.method} ${op.path_template}`}
            className="rounded px-2 py-1 text-[10px] text-[#89b4fa] hover:bg-[#2e2e2e]">Draft test</button>}</td>
      </tr>)}</tbody>
    </table></div>}
    {!loading && (filteredTotal > PAGE_SIZE || pageFailed) && <nav aria-label="Coverage pages" className="mt-4 flex gap-2 text-xs text-muted">
      <button type="button" disabled={offset === 0} onClick={() => goToPage(offset - PAGE_SIZE)}
        className="rounded border border-[#2e2e2e] px-3 py-1.5 disabled:opacity-30">Previous page</button>
      {!pageFailed && <button type="button" disabled={offset + PAGE_SIZE >= filteredTotal} onClick={() => goToPage(offset + PAGE_SIZE)}
        className="rounded border border-[#2e2e2e] px-3 py-1.5 disabled:opacity-30">Next page</button>}
    </nav>}
    {!loading && unmatched.length > 0 && <details className="mt-4 rounded border border-[#2e2e2e] bg-[#111] p-3 text-xs text-[#94a3b8]">
      <summary className="cursor-pointer">{unmatched.length} stored case{unmatched.length === 1 ? "" : "s"} not counted as coverage</summary>
      <ul className="mt-2 space-y-1">{unmatched.map((item) => <li key={item.case_id}>
        <span className="text-[#f1f5f9]">{item.name}</span> — {item.reason === "no_observed_operation"
          ? "its request matches no observed operation" : item.reason === "no_reviewed_expectation"
          ? "no allow or deny expectation has been reviewed" : "its request URL is not usable"}
        {item.request ? <span className="ml-2 font-mono text-muted">{item.request}</span> : null}</li>)}</ul>
    </details>}
    {!loading && unattributed.length > 0 && <details className="mt-4 rounded border border-[#2e2e2e] bg-[#111] p-3 text-xs text-[#94a3b8]">
      <summary className="cursor-pointer">{unattributed.length} unattributed assessment{unattributed.length === 1 ? "" : "s"}</summary>
      <ul className="mt-2 space-y-1">{unattributed.map((item) => <li key={item.job_id}>
        Job <span className="font-mono">{item.job_id}</span>
        {item.case_id && <> · Case <span className="font-mono">{item.case_id}</span></>}
        {item.assessment_status && <> · {item.assessment_status}</>}
        {" · "}{item.reason === "no_observed_operation" ? "The recorded request matches no captured operation."
          : item.reason === "no_usable_snapshot" ? "The job has no usable request snapshot." : item.reason}
      </li>)}</ul>
    </details>}
  </Panel>;
}
