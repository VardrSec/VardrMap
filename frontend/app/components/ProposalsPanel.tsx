"use client";

import { useCallback, useEffect, useState } from "react";
import { Engagement } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, PrimaryButton, DangerButton } from "./ui";

// A change an MCP agent proposed. It is inert until approved here — the agent cannot apply
// it. reason and source are the agent's own words: untrusted text, rendered only as text.
type Proposal = {
  id: string;
  kind: "scope_in" | "scope_out" | "authorization" | "rate_ceiling";
  payload: Record<string, unknown>;
  reason: string;
  source: string;
  proposed_by: string;
  status: string;
};

const KIND_LABEL: Record<Proposal["kind"], string> = {
  scope_in: "Add in-scope",
  scope_out: "Add out-of-scope",
  authorization: "Add authorization",
  rate_ceiling: "Set request-rate ceiling",
};

function summarize(p: Proposal): string {
  const v = p.payload;
  if (p.kind === "scope_in" || p.kind === "scope_out") {
    const sev = v.max_severity ? ` · max ${String(v.max_severity)}` : "";
    return `${String(v.value ?? "")} (${String(v.kind ?? "domain")})${sev}`;
  }
  if (p.kind === "rate_ceiling") return `${String(v.rate ?? "")} requests/sec`;
  if (p.kind === "authorization") {
    return [v.reference, v.permits].filter(Boolean).map(String).join(" · ") || "authorization record";
  }
  return "";
}

export default function ProposalsPanel({ engagement }: { engagement: Engagement }) {
  const { authFetch, setMessage, refreshSelectedEngagement } = useAppContext();
  const [proposals, setProposals] = useState<Proposal[]>([]);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`/engagements/${engagement.id}/proposals?status=pending`);
      if (!res.ok) return;
      const data = await res.json();
      setProposals(Array.isArray(data?.proposals) ? data.proposals : []);
    } catch {
      /* a failed load just leaves the panel empty; it is not an engagement-blocking error */
    }
  }, [authFetch, engagement.id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function resolve(id: string, action: "approve" | "reject") {
    try {
      const res = await authFetch(`/engagements/${engagement.id}/proposals/${id}/${action}`, { method: "POST" });
      if (!res.ok) throw new Error();
      await load();
      if (action === "approve") await refreshSelectedEngagement(engagement.id);
      setMessage(action === "approve" ? "Proposal approved." : "Proposal rejected.");
    } catch {
      setMessage(`Failed to ${action} the proposal.`);
    }
  }

  if (proposals.length === 0) return null;

  return (
    <Panel title={`Proposed changes (${proposals.length})`}>
      <p className="mb-3 text-xs text-muted">
        Changes an AI agent proposed. Nothing takes effect until you approve it. Review the
        reason and source — both come from the agent and are not verified.
      </p>
      <div className="flex flex-col gap-3">
        {proposals.map((p) => (
          <div key={p.id} className="rounded-lg border border-[#2e2e2e] bg-[#161616] px-4 py-3">
            <div className="text-sm font-medium text-[#f1f5f9]">
              {KIND_LABEL[p.kind]}: {summarize(p)}
            </div>
            {p.reason && <div className="mt-1 text-xs text-muted">Reason: {p.reason}</div>}
            {p.source && <div className="mt-0.5 break-all text-xs text-muted">Source: {p.source}</div>}
            {p.proposed_by && <div className="mt-0.5 text-xs text-muted">Proposed by {p.proposed_by}</div>}
            <div className="mt-3 flex gap-2">
              <PrimaryButton onClick={() => resolve(p.id, "approve")} label="Approve" />
              <DangerButton onClick={() => resolve(p.id, "reject")} label="Reject" />
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}
