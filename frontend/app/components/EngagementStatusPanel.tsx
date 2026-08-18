"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "../context/AppContext";
import type { Client, Engagement } from "../types";
import { Panel, StatusBadge } from "./ui";

/**
 * The operational state of an engagement, in one place.
 *
 * Everything here already existed on the engagement object or behind an existing
 * endpoint — type, status, client, testing window, stop-work, role — but the
 * overview showed only counts, so an operator could not tell whether they were
 * authorized to run anything without going looking. No new backend field is
 * introduced for this.
 *
 * Readiness is deliberately advisory, matching how the policy engine treats
 * scope: it reports what is missing and leaves the decision to the operator.
 */

const NEEDS_CLIENT = ["pentest", "internal"];
const NEEDS_AUTHORIZATION = ["pentest", "red_team"];

type ActiveAuthorization = {
  id: string;
  reference?: string;
  authorized_by?: string;
  window_start?: string;
  window_end?: string;
} | null;

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-[#242424] py-2 last:border-0">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{label}</span>
      <span className="text-right text-xs text-[#cbd5e1]">{children}</span>
    </div>
  );
}

function fmtDate(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

/** What the authorization lookup told us. Failure is not the same as "none". */
type AuthState =
  | { phase: "loading" }
  | { phase: "loaded"; authorization: ActiveAuthorization }
  | { phase: "error" };

export default function EngagementStatusPanel({ engagement }: { engagement: Engagement }) {
  // Remount the stateful body whenever either identity changes. This clears the
  // previous authorization/client synchronously, before the new panel paints,
  // without setting state during render. A client can be linked or unlinked
  // while the engagement id stays the same, so both values belong in the key.
  const stateKey = `${engagement.id}\u0000${engagement.client_id || ""}`;
  return <EngagementStatusPanelState key={stateKey} engagement={engagement} />;
}

function EngagementStatusPanelState({ engagement }: { engagement: Engagement }) {
  const { authFetch } = useAppContext();
  const [authState, setAuthState] = useState<AuthState>({ phase: "loading" });
  const [client, setClient] = useState<Client | null>(null);

  const type = engagement.engagement_type || "bug_bounty";
  const wantsClient = NEEDS_CLIENT.includes(type);
  const wantsAuthorization = NEEDS_AUTHORIZATION.includes(type);
  const stopped = Boolean(engagement.stop_work_at);

  const engagementId = engagement.id;
  const clientId = engagement.client_id;

  useEffect(() => {
    // Guards against out-of-order responses: a slow request for the engagement
    // we just left must not overwrite state for the one we are now showing.
    let current = true;

    void (async () => {
      try {
        const res = await authFetch(`/engagements/${engagementId}/authorization/active`);
        if (!current) return;
        if (res.ok) {
          const authorization = await res.json();
          if (current) setAuthState({ phase: "loaded", authorization });
        } else {
          setAuthState({ phase: "error" });
        }
      } catch {
        if (current) setAuthState({ phase: "error" });
      }
    })();

    if (clientId) {
      void (async () => {
        try {
          const res = await authFetch(`/clients/${clientId}`);
          if (!current) return;
          if (res.ok) {
            const loadedClient = await res.json();
            if (current) setClient(loadedClient);
          }
        } catch { /* falls back to showing the id */ }
      })();
    }

    return () => { current = false; };
  }, [authFetch, engagementId, clientId]);

  const auth = authState.phase === "loaded" ? authState.authorization : null;

  // What the operator still has to do before this engagement is properly set up.
  // A failed lookup contributes nothing: we do not know whether it is a gap.
  const gaps: string[] = [];
  if (wantsClient && !engagement.client_id) gaps.push("No client linked");
  if (wantsAuthorization && authState.phase === "loaded" && !auth) {
    gaps.push("No active authorization on record");
  }
  if (wantsAuthorization && !engagement.starts_at && !engagement.ends_at) gaps.push("No testing window set");
  if ((engagement.scope?.in?.length ?? 0) === 0) gaps.push("No in-scope assets defined");

  const windowText =
    engagement.starts_at || engagement.ends_at
      ? `${fmtDate(engagement.starts_at)} → ${fmtDate(engagement.ends_at) === "—" ? "open-ended" : fmtDate(engagement.ends_at)}`
      : "Not set";

  return (
    <Panel title="Engagement Status">
      {stopped && (
        <div className="mb-3 rounded-md border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-300">
          <span className="font-semibold">Stop-work engaged.</span>{" "}
          Every execution for this engagement is refused until it is released.
          {engagement.stop_work_reason ? ` Reason: ${engagement.stop_work_reason}` : ""}
        </div>
      )}

      <div className="grid gap-x-8 md:grid-cols-2">
        <div>
          <Row label="Type"><StatusBadge status={type} /></Row>
          <Row label="Status"><StatusBadge status={engagement.engagement_status || "active"} /></Row>
          <Row label="Your role"><StatusBadge status={engagement.my_role || "owner"} /></Row>
          <Row label="Client">
            {engagement.client_id
              ? (client?.name ?? engagement.client_id)
              : <span className="text-[#52525b]">{wantsClient ? "Not linked" : "Not applicable"}</span>}
          </Row>
        </div>

        <div>
          <Row label="Testing window">{windowText}</Row>
          <Row label="Authorization">
            {authState.phase === "loading" ? (
              <span className="text-[#52525b]">checking…</span>
            ) : authState.phase === "error" ? (
              // "Could not check" is not "none on record". Reporting a failed
              // lookup as an absent authorization would tell an operator they
              // are unauthorized when they may not be, and the reverse once the
              // request succeeds — so it says what actually happened.
              <span className="text-[#f38ba8]">Unavailable — could not check</span>
            ) : auth ? (
              <span className="text-emerald-400">
                Active{auth.reference ? ` · ${auth.reference}` : ""}
              </span>
            ) : wantsAuthorization ? (
              <span className="text-[#f59e0b]">None on record</span>
            ) : (
              // Bounty work is authorized by the programme's published policy,
              // not by a document held here.
              <span className="text-[#52525b]">Programme policy</span>
            )}
          </Row>
          <Row label="Findings">{engagement.findings_count}</Row>
          <Row label="Reports">{engagement.reports_count}</Row>
        </div>
      </div>

      {gaps.length > 0 && (
        <div className="mt-3 rounded-md border border-[#f59e0b]/30 bg-[#f59e0b]/5 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-[#f59e0b]">Setup incomplete</p>
          <ul className="mt-1 space-y-0.5">
            {gaps.map((gap) => (
              <li key={gap} className="text-[11px] leading-tight text-[#cbd5e1]">· {gap}</li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
