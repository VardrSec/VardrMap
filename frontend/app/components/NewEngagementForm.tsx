"use client";

import { useCallback, useEffect, useState } from "react";
import { useAppContext } from "../context/AppContext";
import type { Client, EngagementStatus, EngagementType } from "../types";

/**
 * Creating an engagement is where the platform's shape is decided, so the form
 * asks for it rather than defaulting silently.
 *
 * The API still defaults an omitted `engagement_type` to `bug_bounty` for
 * existing callers, but the UI has no reason to inherit that: a pentest created
 * through this form used to land as a bounty programme with no client, no window
 * and no authorization prompt. Pentest leads here instead.
 *
 * Fields are conditional on type because the requirements genuinely differ —
 * asking a bounty hunter for a client record is noise, and letting a pentest be
 * created without one hides a gap that matters at report time.
 */

const TYPES: { value: EngagementType; label: string; hint: string }[] = [
  { value: "pentest",   label: "Pentest",    hint: "Client engagement under a written authorization." },
  { value: "red_team",  label: "Red Team",   hint: "Objective-based operation under a written authorization." },
  { value: "internal",  label: "Internal",   hint: "Assessment of your own organisation's systems." },
  { value: "bug_bounty", label: "Bug Bounty", hint: "Public or private programme; the programme policy is the authority." },
];

const STATUSES: EngagementStatus[] = ["planned", "active", "reporting", "closed"];

/** Types performed for a named client organisation. */
const NEEDS_CLIENT: EngagementType[] = ["pentest", "internal"];
/** Types that must not run without a written permission-to-test record. */
const NEEDS_AUTHORIZATION: EngagementType[] = ["pentest", "red_team"];
/** Types with a contracted testing window. Bounty work is open-ended. */
const NEEDS_WINDOW: EngagementType[] = ["pentest", "red_team", "internal"];

const inputCls =
  "w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-1.5 text-xs text-[#f1f5f9] placeholder-[#3a3a3a] transition focus:border-[#f59e0b] focus:outline-none";

type Props = { onCreated: (id: string) => void; onMessage: (text: string) => void };

export default function NewEngagementForm({ onCreated, onMessage }: Props) {
  const { authFetch } = useAppContext();

  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("");
  const [programUrl, setProgramUrl] = useState("");
  const [type, setType] = useState<EngagementType>("pentest");
  const [status, setStatus] = useState<EngagementStatus>("planned");
  const [clientId, setClientId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(false);

  const wantsClient = NEEDS_CLIENT.includes(type);
  const wantsAuthorization = NEEDS_AUTHORIZATION.includes(type);
  const wantsWindow = NEEDS_WINDOW.includes(type);

  const loadClients = useCallback(async () => {
    try {
      const res = await authFetch("/clients");
      if (!res.ok) return;
      const data = await res.json();
      setClients(Array.isArray(data) ? data : []);
    } catch { /* the picker just offers no options */ }
  }, [authFetch]);

  useEffect(() => { void loadClients(); }, [loadClients]);

  async function submit() {
    if (!name.trim()) return;
    setLoading(true);
    try {
      // Only send what applies. A bounty engagement carries no client or window,
      // and sending empty strings would store them as set-but-blank.
      const body: Record<string, unknown> = {
        name: name.trim(),
        platform,
        program_url: programUrl,
        engagement_type: type,
        engagement_status: status,
      };
      if (wantsClient && clientId) body.client_id = clientId;
      if (wantsWindow && startsAt) body.starts_at = startsAt;
      if (wantsWindow && endsAt) body.ends_at = endsAt;

      const res = await authFetch("/engagements", { method: "POST", body: JSON.stringify(body) });
      if (!res.ok) throw new Error();
      const created = await res.json();
      setName(""); setPlatform(""); setProgramUrl("");
      setClientId(""); setStartsAt(""); setEndsAt("");
      onCreated(created.id);
      onMessage(
        wantsAuthorization
          ? "Engagement created. Record the authorization before running any jobs."
          : "Engagement created.",
      );
    } catch {
      onMessage("Failed to create engagement.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">New Engagement</p>

      <input className={inputCls} placeholder="Engagement name" aria-label="Engagement name"
        value={name} onChange={(e) => setName(e.target.value)} />

      <select className={inputCls} aria-label="Engagement type"
        value={type} onChange={(e) => setType(e.target.value as EngagementType)}>
        {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
      </select>
      <p className="text-[9px] leading-tight text-[#52525b]">
        {TYPES.find((t) => t.value === type)?.hint}
      </p>

      <select className={inputCls} aria-label="Engagement status"
        value={status} onChange={(e) => setStatus(e.target.value as EngagementStatus)}>
        {STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
      </select>

      {wantsClient && (
        clients.length > 0 ? (
          <select className={inputCls} aria-label="Client"
            value={clientId} onChange={(e) => setClientId(e.target.value)}>
            <option value="">Select a client…</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        ) : (
          <p className="text-[9px] leading-tight text-[#f59e0b]">
            No clients yet — add one in Settings to attribute this engagement.
          </p>
        )
      )}

      {wantsWindow && (
        <div className="grid grid-cols-2 gap-2">
          <input type="date" className={inputCls} aria-label="Start date"
            value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
          <input type="date" className={inputCls} aria-label="End date"
            value={endsAt} onChange={(e) => setEndsAt(e.target.value)} />
        </div>
      )}

      {wantsAuthorization && (
        <p className="rounded-md border border-[#f59e0b]/30 bg-[#f59e0b]/5 px-2 py-1.5 text-[9px] leading-tight text-[#f59e0b]">
          Requires a written authorization before testing. Record it on the
          engagement once created.
        </p>
      )}

      <input className={inputCls} placeholder="Platform (optional)" aria-label="Platform"
        value={platform} onChange={(e) => setPlatform(e.target.value)} />
      <input className={inputCls} placeholder="Engagement URL (optional)" aria-label="Engagement URL"
        value={programUrl} onChange={(e) => setProgramUrl(e.target.value)} />

      <button onClick={submit} disabled={loading || !name.trim()}
        className="w-full rounded-md bg-[#f59e0b] px-3 py-1.5 text-xs font-semibold text-[#161616] transition hover:bg-[#fbbf24] active:scale-[0.98] disabled:opacity-50">
        {loading ? "Working…" : "Create Engagement"}
      </button>
    </div>
  );
}
