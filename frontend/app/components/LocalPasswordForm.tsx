"use client";

import { useState } from "react";
import { useAppContext } from "../context/AppContext";

export default function LocalPasswordForm({ onChanged = () => window.location.reload() }: { onChanged?: () => void }) {
  const { authFetch } = useAppContext();
  const [current, setCurrent] = useState("");
  const [replacement, setReplacement] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (replacement !== confirm) { setMessage("New passwords do not match."); return; }
    setBusy(true); setMessage("");
    try {
      const response = await authFetch("/auth/local/password", { method: "POST", body: JSON.stringify({ current_password: current, new_password: replacement }) });
      if (!response.ok) throw new Error();
      onChanged();
    } catch { setMessage("Password change failed. Check your current password or try again later."); }
    finally { setCurrent(""); setReplacement(""); setConfirm(""); setBusy(false); }
  }
  return <form onSubmit={submit} className="space-y-3 rounded-lg border border-[#2e2e2e] p-4">
    <h3 className="text-sm font-semibold">Local account password</h3>
    <p className="text-xs text-muted">Use a 15–128-character passphrase. Changing it signs out your other local browser sessions.</p>
    {message && <p role="alert" className="text-sm text-red-400">{message}</p>}
    <label className="block text-sm">Current password<input type="password" autoComplete="current-password" required maxLength={128} value={current} onChange={event => setCurrent(event.target.value)} className="ml-2 rounded border border-[#3a3a3a] bg-[#161616] p-2" /></label>
    <label className="block text-sm">New password<input type="password" autoComplete="new-password" required minLength={15} maxLength={128} value={replacement} onChange={event => setReplacement(event.target.value)} className="ml-2 rounded border border-[#3a3a3a] bg-[#161616] p-2" /></label>
    <label className="block text-sm">Confirm new password<input type="password" autoComplete="new-password" required minLength={15} maxLength={128} value={confirm} onChange={event => setConfirm(event.target.value)} className="ml-2 rounded border border-[#3a3a3a] bg-[#161616] p-2" /></label>
    <button disabled={busy} className="rounded bg-[#f59e0b] px-3 py-2 text-sm text-[#161616] disabled:opacity-50">{busy ? "Updating…" : "Change password"}</button>
  </form>;
}
