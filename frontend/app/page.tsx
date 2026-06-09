"use client";

import { useState } from "react";
import { signIn, signOut } from "next-auth/react";
import { Section } from "./types";
import { AppProvider, normalizeProgram, useAppContext } from "./context/AppContext";
import DashboardSection  from "./components/DashboardSection";
import ScopeSection      from "./components/ScopeSection";
import RunSection        from "./components/RunSection";
import ReviewSection     from "./components/ReviewSection";
import FindingsSection   from "./components/FindingsSection";
import ReportsSection    from "./components/ReportsSection";
import SettingsSection   from "./components/SettingsSection";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NAV_ITEMS: { section: Section; label: string; icon: string }[] = [
  { section: "dashboard", label: "Dashboard", icon: "⬡" },
  { section: "scope",     label: "Scope",     icon: "◎" },
  { section: "run",       label: "Run",       icon: "▣" },
  { section: "review",    label: "Review",    icon: "⊹" },
  { section: "findings",  label: "Findings",  icon: "⚑" },
  { section: "reports",   label: "Reports",   icon: "◧" },
  { section: "settings",  label: "Settings",  icon: "◆" },
];

// ---------------------------------------------------------------------------
// App shell — rendered inside AppProvider so it can call useAppContext
// ---------------------------------------------------------------------------

function AppShell() {
  const {
    state, selectedProgram, authFetch, setMessage,
    selectProgram, navigate, loadPrograms,
  } = useAppContext();
  const { session, authLoading, programs, selectedProgramId, activeSection, message } = state;

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [newProgram, setNewProgram] = useState({ name: "", platform: "", program_url: "" });
  const [loading, setLoading] = useState(false);

  async function createProgram() {
    if (!newProgram.name.trim()) return;
    setLoading(true);
    try {
      const res = await authFetch("/programs", { method: "POST", body: JSON.stringify(newProgram) });
      if (!res.ok) throw new Error();
      const created = normalizeProgram(await res.json());
      await loadPrograms();
      selectProgram(created.id);
      setNewProgram({ name: "", platform: "", program_url: "" });
      setMessage("Program created.");
    } catch { setMessage("Failed to create program."); } finally { setLoading(false); }
  }

  const isError = message.toLowerCase().includes("fail") ||
                  message.toLowerCase().includes("error") ||
                  message.toLowerCase().includes("expired");

  // ---------------------------------------------------------------------------
  // Loading / login screens
  // ---------------------------------------------------------------------------

  if (authLoading) {
    return (
      <main className="min-h-screen bg-[#161616] text-[#f1f5f9] flex items-center justify-center">
        <div className="flex items-center gap-3 text-[#52525b]">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#7f849c]" />
          <span className="text-sm tracking-wide font-mono">initializing…</span>
        </div>
      </main>
    );
  }

  if (!session?.backendToken) {
    return (
      <main className="min-h-screen bg-[#161616] text-[#f1f5f9] flex items-center justify-center p-6">
        <div className="w-full max-w-sm rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-10 text-center shadow-2xl">
          <div className="mx-auto mb-5 flex h-10 w-10 items-center justify-center rounded-xl bg-[#2e2e2e] text-[#f59e0b]">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-[#f1f5f9]">VardrMap</h1>
          <p className="mt-2 text-sm text-[#52525b]">Sign in with GitHub to access your private bug bounty workspace.</p>
          <button onClick={() => signIn("github")} className="mt-7 w-full rounded-lg bg-[#f59e0b] px-4 py-2.5 text-sm font-semibold text-[#161616] transition hover:bg-[#fbbf24] active:scale-[0.98]">
            Sign in with GitHub
          </button>
        </div>
      </main>
    );
  }

  // ---------------------------------------------------------------------------
  // App shell
  // ---------------------------------------------------------------------------

  return (
    <main className="min-h-screen bg-[#161616] text-[#f1f5f9]">
      <div className={`grid min-h-screen transition-all duration-200 ${sidebarCollapsed ? "grid-cols-1 lg:grid-cols-[52px_1fr]" : "grid-cols-1 lg:grid-cols-[240px_1fr]"}`}>

        {/* Sidebar */}
        <aside className="flex flex-col border-r border-[#2e2e2e] bg-[#1a1a1a] overflow-hidden">

          {/* Brand */}
          <div className="flex items-center justify-between gap-2 border-b border-[#2e2e2e] px-3 py-4">
            {!sidebarCollapsed && (
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-base font-bold tracking-tight text-[#f1f5f9]">VardrMap</span>
                  <span className="rounded bg-[#2e2e2e] px-1.5 py-0.5 font-mono text-[9px] text-[#52525b]">BETA</span>
                </div>
                <p className="mt-0.5 truncate text-[10px] text-[#52525b]">
                  {session.user?.username || session.user?.email || "GitHub user"}
                </p>
              </div>
            )}
            <button onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="flex-shrink-0 rounded-md p-1.5 text-[#52525b] transition hover:bg-[#2e2e2e] hover:text-[#f1f5f9]"
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                {sidebarCollapsed ? <polyline points="9 18 15 12 9 6" /> : <polyline points="15 18 9 12 15 6" />}
              </svg>
            </button>
          </div>

          {/* Program selector */}
          {!sidebarCollapsed && (
            <div className="border-b border-[#2e2e2e] px-3 py-3">
              <label className="mb-1.5 block text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">Active Program</label>
              <select className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-1.5 text-xs text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none"
                value={selectedProgramId} onChange={(e) => selectProgram(e.target.value)}>
                <option value="">Choose a program</option>
                {programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
          )}

          {/* Nav */}
          <nav className="flex-1 space-y-0.5 px-2 py-3">
            {NAV_ITEMS.map(({ section, label, icon }) => (
              <button key={section} onClick={() => navigate(section)}
                className={`group relative flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-all duration-150 ${activeSection === section ? "bg-[#f59e0b]/10 text-[#f59e0b] font-semibold" : "text-[#52525b] hover:bg-[#242424] hover:text-[#94a3b8]"}`}
                title={sidebarCollapsed ? label : undefined}>
                {activeSection === section && <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[#f59e0b]" />}
                <span className="flex-shrink-0 font-mono text-xs text-[#f59e0b]">{icon}</span>
                {!sidebarCollapsed && <span className="text-xs font-medium">{label}</span>}
              </button>
            ))}
          </nav>

          {/* Create program + sign out */}
          {!sidebarCollapsed && (
            <div className="border-t border-[#2e2e2e] px-3 py-4 space-y-2">
              <p className="text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">New Program</p>
              <input className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-1.5 text-xs text-[#f1f5f9] placeholder-[#3a3a3a] transition focus:border-[#f59e0b] focus:outline-none"
                placeholder="Program name" value={newProgram.name} onChange={(e) => setNewProgram({ ...newProgram, name: e.target.value })} />
              <input className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-1.5 text-xs text-[#f1f5f9] placeholder-[#3a3a3a] transition focus:border-[#f59e0b] focus:outline-none"
                placeholder="Platform" value={newProgram.platform} onChange={(e) => setNewProgram({ ...newProgram, platform: e.target.value })} />
              <input className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-1.5 text-xs text-[#f1f5f9] placeholder-[#3a3a3a] transition focus:border-[#f59e0b] focus:outline-none"
                placeholder="Program URL" value={newProgram.program_url} onChange={(e) => setNewProgram({ ...newProgram, program_url: e.target.value })} />
              <button onClick={createProgram} disabled={loading}
                className="w-full rounded-md bg-[#f59e0b] px-3 py-1.5 text-xs font-semibold text-[#161616] transition hover:bg-[#fbbf24] active:scale-[0.98] disabled:opacity-50">
                {loading ? "Working…" : "Create Program"}
              </button>
              <button onClick={() => signOut({ callbackUrl: "/" })}
                className="w-full rounded-md border border-[#2e2e2e] px-3 py-1.5 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                Sign out
              </button>
            </div>
          )}
        </aside>

        {/* Main content */}
        <section className="min-w-0 overflow-auto p-6 lg:p-8">

          {message && (
            <div className={`mb-5 flex items-center gap-2.5 rounded-lg border px-4 py-3 text-sm ${isError ? "border-red-900 bg-red-950/30 text-red-300" : "border-[#a6e3a1]/20 bg-[#a6e3a1]/5 text-[#a6e3a1]"}`}>
              <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${isError ? "bg-red-400" : "bg-[#a6e3a1]"}`} />
              {message}
            </div>
          )}

          {activeSection === "settings" ? (
            <SettingsSection />
          ) : !selectedProgram ? (
            <div className="rounded-2xl border border-dashed border-[#2e2e2e] p-14 text-center">
              <p className="text-sm text-[#3a3a3a]">Create or select a program to begin.</p>
            </div>
          ) : (
            <>
              {activeSection === "dashboard" && <DashboardSection program={selectedProgram} />}
              {activeSection === "scope"     && <ScopeSection     program={selectedProgram} />}
              {activeSection === "run"       && <RunSection       program={selectedProgram} />}
              {activeSection === "review"    && <ReviewSection    program={selectedProgram} />}
              {activeSection === "findings"  && <FindingsSection  program={selectedProgram} />}
              {activeSection === "reports"   && <ReportsSection   program={selectedProgram} />}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Root — wraps AppShell in the context provider
// ---------------------------------------------------------------------------

export default function Home() {
  return <AppProvider><AppShell /></AppProvider>;
}
