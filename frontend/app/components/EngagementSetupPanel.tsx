"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "../context/AppContext";
import type { Client, Engagement } from "../types";
import { Panel, PrimaryButton } from "./ui";

/**
 * Where a researcher records who the work is for and what permits it.
 *
 * The backend always supported clients, the testing window and written
 * authorization records, but the interface only displayed them, so the only way
 * to create one was a direct API call. This panel is the supported path. It
 * records facts; it does not gate anything — scope and authorization stay
 * advisory, as the policy engine treats them.
 */

const FIELD =
  "w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none";
const LABEL = "mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-muted";

function Field({ label, value, onChange, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; type?: string;
}) {
  return (
    <label className="block">
      <span className={LABEL}>{label}</span>
      <input className={FIELD} type={type} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

/** datetime-local has no zone; the backend stores zone-aware ISO timestamps. */
function toIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function toLocalInput(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const EMPTY_AUTH = { authorized_by: "", reference: "", permits: "", window_start: "", window_end: "" };

export default function EngagementSetupPanel({ engagement, onChanged }: {
  engagement: Engagement;
  /** Called after a record is saved so sibling panels can re-read it. */
  onChanged?: () => void;
}) {
  const { authFetch, setMessage, refreshSelectedEngagement } = useAppContext();
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState(engagement.client_id || "");
  const [newClient, setNewClient] = useState("");
  const [startsAt, setStartsAt] = useState(toLocalInput(engagement.starts_at));
  const [endsAt, setEndsAt] = useState(toLocalInput(engagement.ends_at));
  const [auth, setAuth] = useState(EMPTY_AUTH);
  const readOnly = engagement.my_role === "viewer";

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch("/clients");
        if (!res.ok || cancelled) return;
        const data = await res.json();
        if (!cancelled) setClients(Array.isArray(data) ? data : []);
      } catch { /* the picker simply offers no existing clients */ }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);

  async function patchEngagement(body: Record<string, unknown>, done: string) {
    const res = await authFetch(`/engagements/${engagement.id}`, { method: "PATCH", body: JSON.stringify(body) });
    if (!res.ok) throw new Error();
    await refreshSelectedEngagement(engagement.id);
    onChanged?.();
    setMessage(done);
  }

  async function saveClient() {
    try {
      let id = clientId;
      if (newClient.trim()) {
        const res = await authFetch("/clients", { method: "POST", body: JSON.stringify({ name: newClient.trim() }) });
        if (!res.ok) throw new Error();
        const created = (await res.json()) as Client;
        setClients((prev) => [...prev, created]);
        setNewClient("");
        setClientId(created.id);
        id = created.id;
      }
      if (!id) { setMessage("Choose a client or enter a new client name."); return; }
      await patchEngagement({ client_id: id }, "Client linked.");
    } catch { setMessage("Failed to save client."); }
  }

  async function saveWindow() {
    const starts = toIso(startsAt);
    const ends = toIso(endsAt);
    if (!starts && !ends) { setMessage("Enter a start or end for the testing window."); return; }
    if (starts && ends && new Date(ends) <= new Date(starts)) {
      setMessage("The testing window must end after it starts.");
      return;
    }
    try {
      await patchEngagement(
        { ...(starts ? { starts_at: starts } : {}), ...(ends ? { ends_at: ends } : {}) },
        "Testing window saved.",
      );
    } catch { setMessage("Failed to save testing window."); }
  }

  async function recordAuthorization() {
    if (!auth.authorized_by.trim() || !auth.permits.trim()) {
      setMessage("Authorization needs who authorized the work and what it permits.");
      return;
    }
    const start = toIso(auth.window_start);
    const end = toIso(auth.window_end);
    if (start && end && new Date(end) <= new Date(start)) {
      setMessage("The authorization window must end after it starts.");
      return;
    }
    try {
      const res = await authFetch(`/engagements/${engagement.id}/authorizations`, {
        method: "POST",
        body: JSON.stringify({
          authorized_by: auth.authorized_by.trim(),
          reference: auth.reference.trim(),
          permits: auth.permits.trim(),
          ...(start ? { window_start: start } : {}),
          ...(end ? { window_end: end } : {}),
        }),
      });
      if (!res.ok) throw new Error();
      setAuth(EMPTY_AUTH);
      onChanged?.();
      setMessage("Authorization recorded.");
    } catch { setMessage("Failed to record authorization."); }
  }

  if (readOnly) return null;

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Panel title="Client & testing window">
        <div className="grid gap-3">
          <label className="block">
            <span className={LABEL}>Client</span>
            <select className={FIELD} value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">No client selected</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <Field label="New client name" value={newClient} onChange={setNewClient} />
          <PrimaryButton onClick={saveClient} label="Save client" />
          <Field label="Testing window starts" type="datetime-local" value={startsAt} onChange={setStartsAt} />
          <Field label="Testing window ends" type="datetime-local" value={endsAt} onChange={setEndsAt} />
          <PrimaryButton onClick={saveWindow} label="Save testing window" />
        </div>
      </Panel>
      <Panel title="Written authorization">
        <p className="mb-3 text-xs text-muted">
          Record the permission to test. Superseding an authorization later creates a new record
          rather than editing this one.
        </p>
        <div className="grid gap-3">
          <Field label="Authorized by" value={auth.authorized_by} onChange={(v) => setAuth({ ...auth, authorized_by: v })} />
          <Field label="Reference" value={auth.reference} onChange={(v) => setAuth({ ...auth, reference: v })} />
          <Field label="Permits" value={auth.permits} onChange={(v) => setAuth({ ...auth, permits: v })} />
          <Field label="Authorization window starts" type="datetime-local" value={auth.window_start} onChange={(v) => setAuth({ ...auth, window_start: v })} />
          <Field label="Authorization window ends" type="datetime-local" value={auth.window_end} onChange={(v) => setAuth({ ...auth, window_end: v })} />
          <PrimaryButton onClick={recordAuthorization} label="Record authorization" />
        </div>
      </Panel>
    </div>
  );
}
