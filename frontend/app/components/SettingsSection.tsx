"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiKey } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, Input, PrimaryButton, DangerButton, SectionHeader } from "./ui";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const SEVERITIES = ["info", "low", "medium", "high", "critical"] as const;

export default function SettingsSection() {
  const { authFetch, setMessage } = useAppContext();
  const [keys,       setKeys]       = useState<ApiKey[]>([]);
  const [label,      setLabel]      = useState("");
  const [keyScope,   setKeyScope]   = useState<"full" | "runner">("full");
  const [newToken,   setNewToken]   = useState<string | null>(null);
  const [webhookUrl,  setWebhookUrl]  = useState("");

  // Connect Runner
  const [runnerToken,    setRunnerToken]    = useState<string | null>(null);
  const [runnerKeyId,    setRunnerKeyId]    = useState<string | null>(null);
  const [verifyState,    setVerifyState]    = useState<"idle" | "checking" | "online" | "offline">("idle");
  const [minSeverity, setMinSeverity] = useState("high");

  const loadKeys = useCallback(async () => {
    try {
      const res = await authFetch("/auth/apikeys");
      if (!res.ok) throw new Error();
      const data = await res.json();
      setKeys(Array.isArray(data?.keys) ? data.keys : []);
    } catch { setMessage("Failed to load API keys."); }
  }, [authFetch, setMessage]);

  useEffect(() => { void loadKeys(); }, [loadKeys]);

  // Notification settings
  useEffect(() => {
    void (async () => {
      try {
        const res = await authFetch("/settings");
        if (!res.ok) return;
        const data = await res.json();
        setWebhookUrl(data.webhook_url ?? "");
        setMinSeverity(data.notify_min_severity ?? "high");
      } catch { /* defaults are fine */ }
    })();
  }, [authFetch]);

  async function saveNotifications() {
    try {
      const res = await authFetch("/settings", {
        method: "PATCH",
        body: JSON.stringify({ webhook_url: webhookUrl, notify_min_severity: minSeverity }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setMessage((err as { detail?: string }).detail || "Failed to save notification settings.");
        return;
      }
      setMessage(webhookUrl ? "Notification settings saved." : "Notifications disabled.");
    } catch { setMessage("Failed to save notification settings."); }
  }

  async function generate() {
    try {
      const res = await authFetch("/auth/apikeys", {
        method: "POST",
        body: JSON.stringify({ label, scope: keyScope }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setMessage((err as { detail?: string }).detail || "Failed to generate API key.");
        return;
      }
      const data = await res.json();
      setNewToken(data.token as string);
      setLabel("");
      setKeyScope("full");
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

  async function generateRunnerKey() {
    if (runnerKeyId) {
      await authFetch(`/auth/apikeys/${runnerKeyId}`, { method: "DELETE" }).catch(() => {});
    }
    try {
      const res = await authFetch("/auth/apikeys", {
        method: "POST",
        body: JSON.stringify({ label: "VardrRunner (connect)", scope: "runner" }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setMessage((err as { detail?: string }).detail || "Failed to generate runner key.");
        return;
      }
      const data = await res.json();
      setRunnerToken(data.token as string);
      setRunnerKeyId(data.id as string);
      setVerifyState("idle");
      await loadKeys();
    } catch { setMessage("Failed to generate runner key."); }
  }

  async function verifyRunner() {
    setVerifyState("checking");
    try {
      const res = await authFetch("/runner/status");
      if (res.ok) {
        const data = await res.json();
        setVerifyState((data as { online?: boolean }).online ? "online" : "offline");
      } else {
        setVerifyState("offline");
      }
    } catch { setVerifyState("offline"); }
  }

  function copyCmd(text: string) {
    void navigator.clipboard.writeText(text);
    setMessage("Copied.");
  }

  function downloadPs1(token: string) {
    const script = [
      "# VardrRunner one-time setup",
      `# Generated ${new Date().toISOString()}`,
      "",
      "# Activate the VardrRunner virtual environment",
      "$venvPaths = @(",
      '  "$env:USERPROFILE\\Documents\\code\\VardrRunner\\.venv\\Scripts\\Activate.ps1",',
      '  "$env:USERPROFILE\\Documents\\code\\VardrRunner\\venv\\Scripts\\Activate.ps1"',
      ")",
      "$activated = $false",
      "foreach ($p in $venvPaths) {",
      "  if (Test-Path $p) { . $p; $activated = $true; break }",
      "}",
      'if (-not $activated) { Write-Error "Could not find VardrRunner venv. Run this from the VardrRunner directory after installing it."; exit 1 }',
      "",
      `vardrrunner login vardrmap --url ${API_URL} --token ${token}`,
      "vardrrunner daemon start",
      "vardrrunner doctor",
    ].join("\r\n");
    const blob = new Blob([script], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "vardrrunner-connect.ps1";
    a.click();
    URL.revokeObjectURL(url);
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

      <Panel title="Connect Runner">
        <p className="mb-4 text-xs text-[#52525b]">
          Generate a runner-scoped key and copy the exact commands to start VardrRunner on your machine.
        </p>

        {!runnerToken ? (
          <PrimaryButton onClick={generateRunnerKey} label="Generate Runner Key" />
        ) : (
          <div className="space-y-4">
            {/* Commands */}
            {[
              {
                id: "login",
                label: "1 · Authenticate",
                cmd: `vardrrunner login vardrmap --url ${API_URL} --token ${runnerToken}`,
              },
              {
                id: "daemon",
                label: "2 · Start daemon",
                cmd: "vardrrunner daemon start",
              },
              {
                id: "doctor",
                label: "3 · Verify tools",
                cmd: "vardrrunner doctor",
              },
            ].map(({ id, label, cmd }) => (
              <div key={id}>
                <div className="mb-1 font-mono text-[10px] uppercase tracking-widest text-[#52525b]">{label}</div>
                <div className="flex items-center gap-2">
                  <code className="flex-1 overflow-x-auto rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 font-mono text-xs text-[#f1f5f9] whitespace-nowrap">
                    {cmd}
                  </code>
                  <button
                    onClick={() => copyCmd(cmd)}
                    className="flex-shrink-0 rounded-md border border-[#2e2e2e] px-3 py-2 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]"
                  >
                    Copy
                  </button>
                </div>
              </div>
            ))}

            {/* Actions row */}
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <button
                onClick={() => downloadPs1(runnerToken)}
                className="rounded-md border border-[#2e2e2e] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-[#94a3b8] transition hover:border-[#3a3a3a] hover:text-[#f1f5f9]"
              >
                Download .ps1
              </button>
              <button
                onClick={verifyRunner}
                disabled={verifyState === "checking"}
                className="rounded-md border border-[#2e2e2e] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition"
                style={{
                  borderColor: verifyState === "online" ? "#a6e3a180" : verifyState === "offline" ? "#f8717180" : "#2e2e2e",
                  color: verifyState === "online" ? "#a6e3a1" : verifyState === "offline" ? "#f87171" : "#94a3b8",
                }}
              >
                {verifyState === "checking" ? "checking…" : verifyState === "online" ? "online ✓" : verifyState === "offline" ? "offline ✗" : "Verify connection"}
              </button>
              <button
                onClick={generateRunnerKey}
                className="ml-auto text-[10px] font-mono text-[#52525b] transition hover:text-[#94a3b8]"
              >
                regenerate key
              </button>
            </div>

            <p className="text-[10px] text-[#3a3a3a]">
              This key is runner-scoped (jobs, imports, heartbeat only). Revoke it from Active Keys below if you need to rotate.
            </p>
          </div>
        )}
      </Panel>

      <Panel title="Generate API Key">
        <div className="space-y-3">
          <Input label="Label (optional, e.g. Burp Suite)" value={label} onChange={setLabel} />
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">
              Scope
            </label>
            <div className="flex gap-2">
              {(["full", "runner"] as const).map((s) => (
                <button key={s} onClick={() => setKeyScope(s)}
                  className="flex-1 rounded-md border px-3 py-2 text-xs font-semibold uppercase tracking-widest transition"
                  style={{
                    borderColor: keyScope === s ? "#f59e0b80" : "#2e2e2e",
                    color: keyScope === s ? "#f59e0b" : "#52525b",
                    backgroundColor: keyScope === s ? "#f59e0b12" : "#161616",
                  }}>
                  {s === "full" ? "Full access" : "Runner only"}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] text-[#52525b]">
              {keyScope === "runner"
                ? "Runner keys can only poll jobs, post imports, and send heartbeats — safe to place on a server."
                : "Full-access keys can call any endpoint."}
            </p>
          </div>
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

      <Panel title="Notifications">
        <div className="space-y-3">
          <Input
            label="Webhook URL (Discord or Slack incoming webhook — leave empty to disable)"
            value={webhookUrl}
            onChange={setWebhookUrl}
          />
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">
              Notify on findings at or above
            </label>
            <div className="flex gap-1.5">
              {SEVERITIES.map((s) => (
                <button key={s} onClick={() => setMinSeverity(s)}
                  className="flex-1 rounded-md border px-2 py-1.5 font-mono text-[11px] uppercase transition"
                  style={{
                    borderColor: minSeverity === s ? "#f59e0b80" : "#2e2e2e",
                    color: minSeverity === s ? "#f59e0b" : "#94a3b8",
                    backgroundColor: minSeverity === s ? "#f59e0b12" : "#161616",
                  }}>
                  {s}
                </button>
              ))}
            </div>
          </div>
          <PrimaryButton onClick={saveNotifications} label="Save Notifications" />
        </div>
        <p className="mt-3 text-xs text-[#52525b]">
          Sends a message when a scan job fails or a nuclei import contains findings at or above the threshold.
          Must be an HTTPS URL.
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
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-[#f1f5f9]">
                      {key.label || <span className="italic text-[#52525b]">unlabeled</span>}
                    </span>
                    <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-widest ${
                      key.scope === "runner"
                        ? "bg-[#f59e0b12] text-[#f59e0b]"
                        : "bg-[#6b7280]/10 text-[#6b7280]"
                    }`}>
                      {key.scope === "runner" ? "runner" : "full"}
                    </span>
                  </div>
                  <div className="mt-0.5 font-mono text-xs text-[#52525b]">
                    Created {key.created_at ? new Date(key.created_at).toLocaleDateString() : "—"}
                    {key.last_used_at && (
                      <span className="ml-3">
                        Last used {new Date(key.last_used_at).toLocaleDateString()}
                      </span>
                    )}
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
