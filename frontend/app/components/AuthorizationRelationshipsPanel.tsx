"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "../context/AppContext";
import type { AuthorizationRelationships } from "../types";
import { Panel } from "./ui";

/**
 * Boundary questions worth putting to the target, derived from the tenants, roles and
 * resource owners a person declared in reviewed cases. They are hypotheses, not
 * findings, and nothing here assumes who should have access.
 */

const BOUNDARY_LABEL: Record<string, string> = {
  cross_tenant: "Different tenant",
  same_tenant_peer: "Same-tenant peer",
  higher_privilege: "Higher role than owner",
  anonymous: "No credentials",
};
const STATUS_LABEL: Record<string, string> = {
  untested: "No evaluated test",
  owner_context_missing: "Cases declare no resource owner",
  reviewed_not_run: "Reviewed, not run",
  inconclusive: "No definite result",
};
const STATUS_COLOR: Record<string, string> = {
  untested: "#6b7280", owner_context_missing: "#c084fc", reviewed_not_run: "#89b4fa", inconclusive: "#f59e0b",
};
const SHOWN = 12;

export default function AuthorizationRelationshipsPanel({ engagementId }: { engagementId: string }) {
  const { authFetch, setMessage } = useAppContext();
  const [result, setResult] = useState<{ key: string; data: AuthorizationRelationships | null }>({ key: "", data: null });
  const [all, setAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await authFetch(`/engagements/${engagementId}/api/relationships?limit=500`);
        if (!res.ok) throw new Error();
        const body = (await res.json()) as AuthorizationRelationships;
        if (!cancelled) setResult({ key: engagementId, data: body });
      } catch {
        if (!cancelled) { setMessage("Failed to load boundary questions."); setResult({ key: engagementId, data: null }); }
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch, engagementId, setMessage]);

  const data = result.key === engagementId ? result.data : null;
  const hypotheses = data?.hypotheses ?? [];
  if (!data || (hypotheses.length === 0 && (data.identities ?? []).length === 0)) return null;
  const shown = all ? hypotheses : hypotheses.slice(0, SHOWN);
  const askable = Object.entries(data.askable_boundaries ?? {}).filter(([, on]) => on).map(([key]) => BOUNDARY_LABEL[key] ?? key);

  return <Panel title="Boundary questions">
    <p className="mb-3 text-xs text-muted">
      Questions worth testing, derived only from the tenants, roles and resource owners you declared in reviewed cases.
      <strong className="text-[#94a3b8]"> They are hypotheses, not findings, and say nothing about who should have access.</strong>
    </p>
    <div className="mb-3 flex flex-wrap gap-2 text-[10px] text-[#94a3b8]">
      <span>Boundaries your identities make testable:</span>
      {askable.length === 0 ? <span className="text-muted">none yet. Declare a tenant or role on identities in a reviewed case.</span>
        : askable.map((label) => <span key={label} className="rounded bg-[#242424] px-2 py-0.5 text-[#f1f5f9]">{label}</span>)}
      {data.tenants.length > 0 && <span>· tenants: <span className="font-mono">{data.tenants.join(", ")}</span></span>}
    </div>
    {(data.identities_without_tenant ?? []).length > 0 && <p className="mb-3 rounded border border-[#3f2f12] bg-[#1a1408] p-2 text-[11px] text-[#fbbf24]">
      No tenant is declared for {data.identities_without_tenant.join(", ")}, so their cross-tenant relationships cannot be established.</p>}
    {hypotheses.length === 0 && <p className="py-4 text-center text-sm text-muted">Every testable boundary has a current, evaluated result on the operations that matter.</p>}
    <ul className="space-y-2">{shown.map((h) => <li key={h.id} className="rounded border border-[#2e2e2e] bg-[#111] p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[#f1f5f9]">{h.operation}</span>
        <span className="rounded bg-[#242424] px-2 py-0.5 text-[10px] text-[#c084fc]">{BOUNDARY_LABEL[h.boundary] ?? h.boundary}</span>
        <span className="text-[10px]" style={{ color: STATUS_COLOR[h.status] ?? "#94a3b8" }}>{STATUS_LABEL[h.status] ?? h.status}</span>
      </div>
      <p className="mt-1 text-[#cbd5e1]">{h.question}</p>
      <ul className="mt-1 list-disc pl-4 text-[10px] text-muted">{h.basis.map((line) => <li key={line}>{line}</li>)}</ul>
    </li>)}</ul>
    {hypotheses.length > SHOWN && <button type="button" onClick={() => setAll(!all)} className="mt-3 text-xs text-[#89b4fa] hover:underline">
      {all ? "Show fewer" : `Show all ${hypotheses.length}`}</button>}
  </Panel>;
}
