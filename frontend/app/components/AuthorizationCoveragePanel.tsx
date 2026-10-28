"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "../context/AppContext";
import type { AuthorizationCoverage, CoverageOperation, CoverageState } from "../types";
import { Panel } from "./ui";

/**
 * Where authorization testing is incomplete, computed by the backend from stored
 * inventory, reviewed cases, executed jobs and their evidence. Nothing here is
 * inferred in the browser, and "conclusive" never means "secure": it repeats the
 * stored assessment (definite reported outcomes with a working baseline).
 */

const STATE_LABEL: Record<CoverageState, string> = {
  violation_candidate: "Violation candidate",
  inconclusive: "Inconclusive",
  partial: "Partial",
  conclusive: "Conclusive",
  reviewed_not_executed: "Reviewed, not executed",
  untested: "No reviewed test",
};
const STATE_COLOR: Record<CoverageState, string> = {
  violation_candidate: "#f87171",
  inconclusive: "#f59e0b",
  partial: "#fbbf24",
  conclusive: "#4ade80",
  reviewed_not_executed: "#89b4fa",
  untested: "#6b7280",
};
const STATE_ORDER: CoverageState[] = [
  "violation_candidate", "inconclusive", "partial", "conclusive", "reviewed_not_executed", "untested",
];
const IDENTITY_LABEL: Record<string, string> = {
  evaluated: "evaluated",
  inconclusive: "inconclusive",
  missing: "no result reported",
  skipped: "no expectation",
  reviewed_not_run: "reviewed, not run",
  not_reviewed: "not reviewed",
};
const IDENTITY_COLOR: Record<string, string> = {
  evaluated: "#4ade80", inconclusive: "#f59e0b", missing: "#f59e0b",
  skipped: "#6b7280", reviewed_not_run: "#89b4fa", not_reviewed: "#52525b",
};

function StateBadge({ state }: { state: CoverageState }) {
  return <span className="rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
    style={{ color: STATE_COLOR[state], background: `${STATE_COLOR[state]}1f` }}>{STATE_LABEL[state]}</span>;
}

export default function AuthorizationCoveragePanel({ engagementId }: { engagementId: string }) {
  const { authFetch, setMessage } = useAppContext();
  const [state, setState] = useState<CoverageState | "">("");
  // Loading is derived from which request the stored result answers, so the effect
  // never sets state synchronously (only after the response arrives).
  const requestKey = `${engagementId}|${state}`;
  const [result, setResult] = useState<{ key: string; data: AuthorizationCoverage | null }>({ key: "", data: null });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const params = new URLSearchParams({ limit: "500" });
        if (state) params.set("state", state);
        const res = await authFetch(`/engagements/${engagementId}/api/coverage?${params}`);
        if (!res.ok) throw new Error();
        const body = (await res.json()) as AuthorizationCoverage;
        if (!cancelled) setResult({ key: requestKey, data: body });
      } catch {
        if (!cancelled) {
          setMessage("Failed to load authorization coverage.");
          setResult({ key: requestKey, data: null });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch, engagementId, requestKey, setMessage, state]);

  const loading = result.key !== requestKey;
  const data = result.data;

  const operations: CoverageOperation[] = data?.operations ?? [];
  const summary = data?.summary;
  if (!loading && (!summary || summary.total === 0)) return null;

  return <Panel title="Authorization coverage">
    <p className="mb-4 text-xs text-muted">
      Which observed operations have a reviewed authorization test, whether it ran, and for which identities.
      <strong className="text-[#94a3b8]"> Conclusive describes reported outcomes with a working baseline; it does not mean the operation is secure.</strong>{" "}
      Identities listed as <em>not reviewed</em> exist elsewhere in this engagement but not in a test for that operation.
    </p>
    {summary && <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-6">
      {STATE_ORDER.map((key) => <button key={key} type="button" aria-pressed={state === key}
        onClick={() => setState(state === key ? "" : key)}
        className="rounded-lg border bg-[#171717] p-3 text-left transition hover:border-[#3a3a3a]"
        style={{ borderColor: state === key ? STATE_COLOR[key] : "#2e2e2e" }}>
        <div className="font-mono text-xl" style={{ color: STATE_COLOR[key] }}>{summary[key]}</div>
        <div className="mt-1 text-[10px] uppercase tracking-widest text-muted">{STATE_LABEL[key]}</div>
      </button>)}
    </div>}
    {loading && <p className="py-6 text-center text-sm text-muted">Computing coverage…</p>}
    {!loading && operations.length === 0 && <p className="py-6 text-center text-sm text-muted">No operations in this state.</p>}
    {!loading && operations.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left text-xs">
      <thead><tr className="border-b border-[#2e2e2e]">{["Operation", "State", "Candidates", "Identities"].map((h) =>
        <th key={h} className="pb-2 pr-4 font-semibold uppercase tracking-widest text-muted">{h}</th>)}</tr></thead>
      <tbody>{operations.map((op) => <tr key={op.endpoint_id} className="border-b border-[#1e1e1e] align-top">
        <td className="py-2.5 pr-4"><div className="font-mono text-[#f1f5f9]">{op.method} {op.path_template}</div>
          <div className="mt-0.5 text-[10px] text-muted">{op.host}</div></td>
        <td className="py-2.5 pr-4"><StateBadge state={op.state} />
          {op.cases.length > 0 && <div className="mt-1 text-[10px] text-muted">{op.cases.length} reviewed case{op.cases.length === 1 ? "" : "s"}</div>}</td>
        <td className="py-2.5 pr-4 font-mono text-[#94a3b8]">{op.candidates.open + op.candidates.promoted > 0
          ? `${op.candidates.open} open · ${op.candidates.promoted} promoted · ${op.candidates.backing_evidence} with evidence` : "—"}</td>
        <td className="py-2.5"><div className="flex flex-wrap gap-1.5">{op.identity_coverage.map((row) =>
          <span key={row.identity_id} title={row.reason ? `${IDENTITY_LABEL[row.state] ?? row.state}: ${row.reason.replace(/_/g, " ")}` : IDENTITY_LABEL[row.state] ?? row.state}
            className="rounded border px-1.5 py-0.5 font-mono text-[10px]"
            style={{ color: IDENTITY_COLOR[row.state] ?? "#94a3b8", borderColor: `${IDENTITY_COLOR[row.state] ?? "#94a3b8"}55` }}>
            {row.identity_id} · {IDENTITY_LABEL[row.state] ?? row.state}
          </span>)}{op.identity_coverage.length === 0 && <span className="text-muted">no identities declared in this engagement</span>}</div></td>
      </tr>)}</tbody>
    </table></div>}
    {!loading && (data?.unmatched_cases.length ?? 0) > 0 && <details className="mt-4 rounded border border-[#2e2e2e] bg-[#111] p-3 text-xs text-[#94a3b8]">
      <summary className="cursor-pointer">{data?.unmatched_cases.length} stored case{data?.unmatched_cases.length === 1 ? "" : "s"} not counted as coverage</summary>
      <ul className="mt-2 space-y-1">{data?.unmatched_cases.map((item) => <li key={item.case_id}>
        <span className="text-[#f1f5f9]">{item.name}</span> — {item.reason === "no_observed_operation"
          ? "its request matches no observed operation" : item.reason === "no_reviewed_expectation"
          ? "no allow or deny expectation has been reviewed" : "its request URL is not usable"}
        {item.request ? <span className="ml-2 font-mono text-muted">{item.request}</span> : null}</li>)}</ul>
    </details>}
  </Panel>;
}
