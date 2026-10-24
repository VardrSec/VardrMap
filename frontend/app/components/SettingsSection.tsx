"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiKey } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, Input, PrimaryButton, DangerButton, SectionHeader } from "./ui";
import { VARDRGATE_VERSION, vardrgateUnixInstallCommand, vardrgateWindowsInstallCommand } from "../lib/vardrgateInstall";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const VARDRUNNER_INSTALL_COMMAND = "pipx install vardrrunner";
// VardrRunner 0.50.0+ updates itself; older copies need one pipx upgrade to get there.
const VARDRUNNER_UPDATE_COMMAND = "vardrrunner update";
const VARDRUNNER_UPGRADE_COMMAND = "pipx upgrade vardrrunner";
const VARDRGATE_RELEASES_URL = "https://github.com/VardrSec/VardrGate/releases/latest";

const SEVERITIES = ["info", "low", "medium", "high", "critical"] as const;

const VARDRUNNER_TOOLS_COMMAND = "vardrrunner tools install --all";
const VARDRUNNER_HEARTBEAT_COMMAND = "vardrrunner heartbeat";
const VARDRUNNER_JOBS_COMMAND = "vardrrunner jobs run";

// The key is deliberately not part of the command: `init` reads it from a hidden prompt, so it
// never lands in shell history, and stores it in the OS keychain. Tools are their own step.
// No startup service: VardrRunner runs only when invoked, and rejects `--install-service`.
export function runnerInitCommand(apiUrl: string = API_URL): string {
  return `vardrrunner init --url ${apiUrl} --no-install-tools`;
}

export function engagementCommands(engagementId: string | null): string[] {
  const id = engagementId ?? "<engagement-id>";
  const commands = [`vardrrunner scope ${id}`, `vardrrunner run httpx --engagement ${id} --scope`];
  return engagementId ? commands : ["vardrrunner engagements", ...commands];
}

export default function SettingsSection() {
  const { authFetch, setMessage, selectedEngagement } = useAppContext();
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
              className="flex-shrink-0 rounded-md border border-[#2e2e2e] px-3 py-2 text-xs text-muted transition hover:border-[#3a3a3a] hover:text-muted-hover"
            >
              Copy
            </button>
          </div>
          <button onClick={() => setNewToken(null)} className="text-xs text-muted transition hover:text-muted-hover">
            Dismiss
          </button>
        </div>
      )}

      <Panel title="Connect Runner">
        <p className="mb-5 text-xs text-muted">
          Run these on the computer that will run your scans. Each step has a Copy button.
        </p>

        <div className="space-y-5">
          <Step n={1} title="Install VardrRunner">
            <CopyLine text={VARDRUNNER_INSTALL_COMMAND} onCopy={copyCmd} />
            <Hint>Needs Python 3.10+ and pipx. Already installed? Update it instead:</Hint>
            <CopyLine text={VARDRUNNER_UPDATE_COMMAND} onCopy={copyCmd} />
            <Hint>On VardrRunner 0.49 or older, <span className="font-mono">vardrrunner update</span> doesn&apos;t exist yet. Run this once instead:</Hint>
            <CopyLine text={VARDRUNNER_UPGRADE_COMMAND} onCopy={copyCmd} />
          </Step>

          <Step n={2} title="Get your runner key">
            {!runnerToken ? (
              <PrimaryButton onClick={generateRunnerKey} label="Generate Runner Key" />
            ) : (
              <>
                <CopyLine text={runnerToken} onCopy={copyCmd} />
                <Hint>
                  Shown once. You will paste it in the next step.{" "}
                  <button onClick={generateRunnerKey} className="underline transition hover:text-[#94a3b8]">
                    Generate a new one
                  </button>
                </Hint>
              </>
            )}
          </Step>

          <Step n={3} title="Connect this computer">
            <CopyLine text={runnerInitCommand()} onCopy={copyCmd} />
            <Hint>Paste your key when it asks. Nothing starts in the background or at sign-in: the runner only runs when you run it.</Hint>
          </Step>

          <Step n={4} title="Install or check your tools">
            <CopyLine text={VARDRUNNER_TOOLS_COMMAND} onCopy={copyCmd} />
            <Hint>
              Safe to run any time: installs missing tools, updates old ones, repairs broken ones and skips the ones that are
              fine. It also tells you if nmap or VardrGate is missing. VardrGate has its own step below.
            </Hint>
          </Step>

          <Step n={5} title="Install VardrGate (API assessments only)">
            <Hint>
              Skip this unless you run API assessments. Each command downloads VardrGate v{VARDRGATE_VERSION}, checks it
              against the release&apos;s checksums, refuses it if they don&apos;t match, and puts it on your PATH.
            </Hint>
            <Hint>Windows (PowerShell):</Hint>
            <CopyLine text={vardrgateWindowsInstallCommand()} onCopy={copyCmd} />
            <Hint>macOS or Linux (installs to ~/.local/bin; add that to your PATH if it isn&apos;t already):</Hint>
            <CopyLine text={vardrgateUnixInstallCommand()} onCopy={copyCmd} />
            <Hint>
              Both finish by printing the version. Prefer to do it by hand?{" "}
              <a href={VARDRGATE_RELEASES_URL} target="_blank" rel="noopener noreferrer" className="underline hover:text-[#94a3b8]">
                Download it here
              </a>.
            </Hint>
          </Step>

          <Step n={6} title="Check it's connected">
            <Hint>Report in once, then click Verify within five minutes:</Hint>
            <CopyLine text={VARDRUNNER_HEARTBEAT_COMMAND} onCopy={copyCmd} />
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
            <Hint>Showing offline? This tells you what is wrong and how to fix it:</Hint>
            <CopyLine text="vardrrunner doctor" onCopy={copyCmd} />
          </Step>

          <Step n={7} title="Start on an engagement">
            <Hint>
              {selectedEngagement
                ? `Ready for ${selectedEngagement.name}. Check its scope, then see which in-scope hosts are live:`
                : "List your engagements to get an ID (or open one here to fill it in), check its scope, then see which in-scope hosts are live:"}
            </Hint>
            {engagementCommands(selectedEngagement?.id ?? null).map((cmd) => (
              <CopyLine key={cmd} text={cmd} onCopy={copyCmd} />
            ))}
            <Hint>After that, queue scans from the Jobs tab. They wait until you run them on this computer:</Hint>
            <CopyLine text={VARDRUNNER_JOBS_COMMAND} onCopy={copyCmd} />
          </Step>
        </div>
      </Panel>

      <Panel title="Generate API Key">
        <div className="space-y-3">
          <Input label="Label (optional, e.g. Burp Suite)" value={label} onChange={setLabel} />
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-muted">
              Scope
            </label>
            <div className="flex gap-2">
              {(["full", "runner"] as const).map((s) => (
                <button key={s} onClick={() => setKeyScope(s)}
                  className="flex-1 rounded-md border px-3 py-2 text-xs font-semibold uppercase tracking-widest transition"
                  style={{
                    borderColor: keyScope === s ? "#f59e0b80" : "#2e2e2e",
                    color: keyScope === s ? "#f59e0b" : "var(--color-muted)",
                    backgroundColor: keyScope === s ? "#f59e0b12" : "#161616",
                  }}>
                  {s === "full" ? "Full access" : "Runner only"}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] text-muted">
              {keyScope === "runner"
                ? "Runner keys can only poll jobs, post imports, and send heartbeats — safe to place on a server."
                : "Full-access keys can call any endpoint."}
            </p>
          </div>
          <PrimaryButton onClick={generate} label="Generate Key" />
        </div>
        <p className="mt-3 text-xs text-muted">
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
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-muted">
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
        <p className="mt-3 text-xs text-muted">
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
                      {key.label || <span className="italic text-muted">unlabeled</span>}
                    </span>
                    <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-widest ${
                      key.scope === "runner"
                        ? "bg-[#f59e0b12] text-[#f59e0b]"
                        : "bg-[#6b7280]/10 text-[#6b7280]"
                    }`}>
                      {key.scope === "runner" ? "runner" : "full"}
                    </span>
                  </div>
                  <div className="mt-0.5 font-mono text-xs text-muted">
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

function CopyLine({ text, onCopy }: { text: string; onCopy: (text: string) => void }) {
  return (
    <div className="flex items-center gap-2">
      <code className="flex-1 overflow-x-auto rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 font-mono text-xs text-[#f1f5f9] whitespace-nowrap">
        {text}
      </code>
      <button
        onClick={() => onCopy(text)}
        className="flex-shrink-0 rounded-md border border-[#2e2e2e] px-3 py-2 text-xs text-muted transition hover:border-[#3a3a3a] hover:text-muted-hover"
      >
        Copy
      </button>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 font-mono text-[10px] uppercase tracking-widest text-muted">
        {n} · {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Hint({ children }: { children: ReactNode }) {
  return <p className="text-[10px] text-muted">{children}</p>;
}
