"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiKey, AuthFetch } from "../types";
import { Panel, Input, PrimaryButton, DangerButton, SectionHeader } from "./ui";

export default function SettingsSection({ authFetch, setMessage }: {
  authFetch: AuthFetch;
  setMessage: (m: string) => void;
}) {
  const [keys,     setKeys]     = useState<ApiKey[]>([]);
  const [label,    setLabel]    = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);

  const loadKeys = useCallback(async () => {
    try {
      const res = await authFetch("/auth/apikeys");
      if (!res.ok) throw new Error();
      const data = await res.json();
      setKeys(Array.isArray(data?.keys) ? data.keys : []);
    } catch { setMessage("Failed to load API keys."); }
  }, [authFetch, setMessage]);

  useEffect(() => { void loadKeys(); }, [loadKeys]);

  async function generate() {
    try {
      const res = await authFetch("/auth/apikeys", { method: "POST", body: JSON.stringify({ label }) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setMessage((err as { detail?: string }).detail || "Failed to generate API key.");
        return;
      }
      const data = await res.json();
      setNewToken(data.token as string);
      setLabel("");
      await loadKeys();
    } catch { setMessage("Failed to generate API key."); }
  }

  async function revoke(keyId: string) {
    try {
      await authFetch(`/auth/apikeys/${keyId}`, { method: "DELETE" });
      if (newToken) setNewToken(null);
      await loadKeys();
      setMessage("API key revoked.");
    } catch { setMessage("Failed to revoke API key."); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Settings" description="Manage personal API keys for external tools like Burp Suite." />

      {newToken && (
        <div className="rounded-xl border border-[#a6e3a1]/30 bg-[#a6e3a1]/5 p-5 space-y-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-[#a6e3a1]">
            Copy this token now — it will not be shown again
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 break-all rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 font-mono text-xs text-[#f1f5f9]">
              {newToken}
            </code>
            <button
              onClick={() => { void navigator.clipboard.writeText(newToken); setMessage("Copied."); }}
              className="flex-shrink-0 rounded-md border border-[#2e2e2e] px-3 py-2 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]"
            >
              Copy
            </button>
          </div>
          <button onClick={() => setNewToken(null)} className="text-xs text-[#52525b] transition hover:text-[#94a3b8]">
            Dismiss
          </button>
        </div>
      )}

      <Panel title="Generate API Key">
        <div className="space-y-3">
          <Input label="Label (optional, e.g. Burp Suite)" value={label} onChange={setLabel} />
          <PrimaryButton onClick={generate} label="Generate Key" />
        </div>
        <p className="mt-3 text-xs text-[#52525b]">
          Send as{" "}
          <code className="rounded bg-[#2e2e2e] px-1.5 py-0.5 font-mono text-[#94a3b8]">
            Authorization: Bearer vmap_…
          </code>
          {" "}to authenticate any API request.
        </p>
      </Panel>

      <Panel title="Active Keys">
        {keys.length === 0 ? (
          <p className="text-sm text-[#3a3a3a]">No API keys yet.</p>
        ) : (
          <div className="space-y-2">
            {keys.map((key) => (
              <div key={key.id} className="flex items-center justify-between rounded-lg border border-[#2e2e2e] bg-[#161616] px-4 py-3">
                <div>
                  <div className="text-sm text-[#f1f5f9]">
                    {key.label || <span className="italic text-[#52525b]">unlabeled</span>}
                  </div>
                  <div className="mt-0.5 font-mono text-xs text-[#52525b]">
                    Created {key.created_at ? new Date(key.created_at).toLocaleDateString() : "—"}
                  </div>
                </div>
                <DangerButton onClick={() => revoke(key.id)} label="Revoke" small />
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
