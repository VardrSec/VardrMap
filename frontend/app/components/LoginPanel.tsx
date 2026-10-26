"use client";

import { useEffect, useState } from "react";
import { signIn } from "next-auth/react";
import { API_URL, isSecureApi, selectAuthMethod } from "../auth-client";

export default function LoginPanel({ onSignedIn = () => window.location.reload() }: { onSignedIn?: () => void }) {
  const [methods, setMethods] = useState<string[] | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const secure = typeof window !== "undefined" && window.location.protocol === "https:" && isSecureApi(API_URL);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetch(`${API_URL}/auth/methods`, { cache: "no-store", credentials: "omit", redirect: "error" });
        const data = response.ok ? await response.json() : null;
        if (!Array.isArray(data?.methods) || !data.methods.length || data.methods.some((method: unknown) => method !== "local" && method !== "github")) throw new Error();
        if (active) setMethods(data.methods);
      } catch { if (active) setError("Unable to load sign-in methods. Start the platform and verify its HTTPS certificate is trusted. The administrator may need to finish the backend update."); }
    })();
    return () => { active = false; };
  }, [retry]);

  async function login(event: React.FormEvent) {
    event.preventDefault();
    if (!secure || busy) return;
    setBusy(true); setError("");
    try {
      selectAuthMethod("signed-out");
      const response = await fetch(`${API_URL}/auth/local/login`, {
        method: "POST", credentials: "include", cache: "no-store", redirect: "error",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }),
      });
      if (!response.ok) throw new Error();
      selectAuthMethod("local");
      onSignedIn();
    } catch { setError("Sign-in failed. Check your credentials or try again later."); }
    finally { setPassword(""); setBusy(false); }
  }

  async function loginWithGithub() {
    try {
      selectAuthMethod("github");
      await signIn("github");
    } catch { setError("Unable to start GitHub sign-in. Allow site storage and retry."); }
  }

  return (
    <main className="min-h-screen bg-[#161616] text-[#f1f5f9] flex items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-8 shadow-2xl">
        <h1 className="text-2xl font-bold tracking-tight">VardrMap</h1>
        <p className="mt-2 text-sm text-muted">Access your authorized security testing workspace.</p>
        {!methods && !error && <p className="mt-5 text-sm">Loading sign-in methods…</p>}
        {error && <p role="alert" className="mt-4 text-sm text-red-400">{error}</p>}
        {!methods && error && <button onClick={() => { setError(""); setRetry(value => value + 1); }} className="mt-4 rounded border border-[#3a3a3a] px-4 py-2 text-sm">Retry connection</button>}
        {methods?.includes("local") && (
          <form onSubmit={login} className="mt-6 space-y-4">
            {!secure && <p role="alert" className="text-sm text-amber-400">Local sign-in requires HTTPS for the application and API.</p>}
            <label className="block text-sm">Local username
              <input value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" required maxLength={64} disabled={!secure || busy} className="mt-1 w-full rounded border border-[#3a3a3a] bg-[#161616] p-2" />
            </label>
            <label className="block text-sm">Local password
              <input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" required maxLength={128} disabled={!secure || busy} className="mt-1 w-full rounded border border-[#3a3a3a] bg-[#161616] p-2" />
            </label>
            <button type="submit" disabled={!secure || busy} className="w-full rounded-lg bg-[#f59e0b] px-4 py-2.5 text-sm font-semibold text-[#161616] disabled:opacity-50">{busy ? "Signing in…" : "Sign in locally"}</button>
          </form>
        )}
        {methods?.includes("github") && <button onClick={() => void loginWithGithub()} className="mt-6 w-full rounded-lg bg-[#f59e0b] px-4 py-2.5 text-sm font-semibold text-[#161616]">Sign in with GitHub</button>}
      </div>
    </main>
  );
}
