"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { signIn, signOut } from "next-auth/react";
import { AppSession, FindingFormState, Program, ScanItem, Section } from "./types";
import DashboardSection  from "./components/DashboardSection";
import ProgramSection    from "./components/ProgramSection";
import ScopeSection      from "./components/ScopeSection";
import ImportsSection    from "./components/ImportsSection";
import ReconSection      from "./components/ReconSection";
import ScanningSection   from "./components/ScanningSection";
import ManualSection     from "./components/ManualSection";
import FindingsSection   from "./components/FindingsSection";
import ReportsSection    from "./components/ReportsSection";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const NAV_ITEMS: { section: Section; label: string; icon: string }[] = [
  { section: "dashboard", label: "Dashboard",      icon: "⬡" },
  { section: "program",   label: "Program Profile", icon: "◈" },
  { section: "scope",     label: "Scope",           icon: "◎" },
  { section: "imports",   label: "Imports",         icon: "↓" },
  { section: "recon",     label: "Recon",           icon: "⊹" },
  { section: "scanning",  label: "Scanning",        icon: "◉" },
  { section: "manual",    label: "Manual Testing",  icon: "✦" },
  { section: "findings",  label: "Findings",        icon: "⚑" },
  { section: "reports",   label: "Reports",         icon: "◧" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Defensively coerce every field so components never have to deal with undefined
// coming from the API — e.g. a missing recon_count just becomes 0.
function normalizeProgram(raw: any): Program {
  return {
    id:                 String(raw?.id ?? ""),
    name:               String(raw?.name ?? ""),
    platform:           String(raw?.platform ?? ""),
    program_url:        String(raw?.program_url ?? ""),
    scope_summary:      String(raw?.scope_summary ?? ""),
    severity_guidance:  String(raw?.severity_guidance ?? ""),
    safe_harbor_notes:  String(raw?.safe_harbor_notes ?? ""),
    scope: {
      in:  Array.isArray(raw?.scope?.in)  ? raw.scope.in  : [],
      out: Array.isArray(raw?.scope?.out) ? raw.scope.out : [],
    },
    imports:      Array.isArray(raw?.imports)      ? raw.imports      : [],
    recon_count:  typeof raw?.recon_count  === "number" ? raw.recon_count  : 0,
    scans_count:  typeof raw?.scans_count  === "number" ? raw.scans_count  : 0,
    manual_tests: Array.isArray(raw?.manual_tests) ? raw.manual_tests : [],
    findings:     Array.isArray(raw?.findings)     ? raw.findings     : [],
    reports:      Array.isArray(raw?.reports)      ? raw.reports      : [],
  };
}

async function getFrontendSession(): Promise<AppSession | null> {
  try {
    const res = await fetch("/api/auth/session", { method: "GET", credentials: "include", cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || Object.keys(data).length === 0) return null;
    return data;
  } catch { return null; }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Home() {
  const [session,           setSession]           = useState<AppSession | null>(null);
  const [authLoading,       setAuthLoading]       = useState(true);
  const [programs,          setPrograms]          = useState<Program[]>([]);
  const [selectedProgramId, setSelectedProgramId] = useState("");
  const [activeSection,     setActiveSection]     = useState<Section>("dashboard");
  const [message,           setMessage]           = useState("");
  const [sidebarCollapsed,  setSidebarCollapsed]  = useState(false);
  const [newProgram,        setNewProgram]        = useState({ name: "", platform: "", program_url: "" });
  const [loading,           setLoading]           = useState(false);
  const [findingPrefill,    setFindingPrefill]    = useState<FindingFormState | null>(null);

  // authFetch needs a stable reference (empty deps) so child components can safely
  // put it in their own useEffect dependency arrays without causing infinite loops.
  // A ref lets it always read the latest session without re-creating the function.
  useEffect(() => {
    if (!message) return;
    const id = setTimeout(() => setMessage(""), 4000);
    return () => clearTimeout(id);
  }, [message]);

  const sessionRef = useRef(session);
  useEffect(() => { sessionRef.current = session; }, [session]);

  const selectedProgram = useMemo(
    () => programs.find((p) => p.id === selectedProgramId) ?? null,
    [programs, selectedProgramId],
  );

  const authFetch = useCallback(async (path: string, init: RequestInit = {}) => {
    const current = sessionRef.current ?? (await getFrontendSession());
    if (!current?.backendToken) throw new Error("Not authenticated");
    const headers = new Headers(init.headers || {});
    headers.set("Authorization", `Bearer ${current.backendToken}`);
    if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
    if (response.status === 401) {
      setMessage("Session expired. Please sign in again.");
      throw new Error("Unauthorized");
    }
    return response;
  }, []);

  const refreshSelectedProgram = useCallback(async (programId?: string) => {
    const id = programId || selectedProgramId;
    if (!id) return;
    try {
      const res = await authFetch(`/programs/${id}`);
      if (!res.ok) throw new Error();
      const data = normalizeProgram(await res.json());
      setPrograms((prev) =>
        prev.some((p) => p.id === id) ? prev.map((p) => p.id === id ? data : p) : [...prev, data],
      );
    } catch { setMessage("Failed to refresh program."); }
  }, [selectedProgramId, authFetch]);

  useEffect(() => { void bootstrapSession(); }, []);

  useEffect(() => {
    if (!authLoading && session?.backendToken) {
      void syncUser();
      void loadPrograms();
    }
  }, [authLoading, session?.backendToken]);

  async function bootstrapSession() {
    setAuthLoading(true);
    setSession(await getFrontendSession());
    setAuthLoading(false);
  }

  async function syncUser() {
    try { await authFetch("/auth/sync", { method: "POST" }); } catch { /* non-blocking */ }
  }

  async function loadPrograms() {
    try {
      const res = await authFetch("/programs");
      if (!res.ok) throw new Error();
      const data = await res.json();
      const normalized = Array.isArray(data?.programs) ? data.programs.map(normalizeProgram) : [];
      setPrograms(normalized);
      if (!selectedProgramId && normalized.length > 0) setSelectedProgramId(normalized[0].id);
      if (normalized.length === 0) setSelectedProgramId("");
    } catch { setPrograms([]); setMessage("Failed to load programs."); }
  }

  async function createProgram() {
    if (!newProgram.name.trim()) return;
    setLoading(true); setMessage("");
    try {
      const res = await authFetch("/programs", { method: "POST", body: JSON.stringify(newProgram) });
      if (!res.ok) throw new Error();
      const created = normalizeProgram(await res.json());
      setPrograms((prev) => [...prev, created]);
      setSelectedProgramId(created.id);
      setNewProgram({ name: "", platform: "", program_url: "" });
      setMessage("Program created.");
    } catch { setMessage("Failed to create program."); } finally { setLoading(false); }
  }

  async function deleteProgram() {
    if (!selectedProgramId || !confirm("Delete this program?")) return;
    try {
      const res = await authFetch(`/programs/${selectedProgramId}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      const remaining = programs.filter((p) => p.id !== selectedProgramId);
      setPrograms(remaining);
      setSelectedProgramId(remaining[0]?.id || "");
      setActiveSection("dashboard");
      setMessage("Program deleted.");
    } catch { setMessage("Failed to delete program."); }
  }

  // Pre-fills the findings form from a scan result so the user doesn't have
  // to retype everything. Status starts as "candidate" — it still needs human
  // validation before it becomes a real finding.
  function promoteScanToFinding(scan: ScanItem) {
    setFindingPrefill({
      title: scan.title, severity: scan.severity || "medium",
      asset: scan.asset || "", status: "candidate",
      summary: scan.description || "", steps: "", impact: "", remediation: "",
    });
    setActiveSection("findings");
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
                value={selectedProgramId} onChange={(e) => setSelectedProgramId(e.target.value)}>
                <option value="">Choose a program</option>
                {programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
          )}

          {/* Nav */}
          <nav className="flex-1 space-y-0.5 px-2 py-3">
            {NAV_ITEMS.map(({ section, label, icon }) => (
              <button key={section} onClick={() => setActiveSection(section)}
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

          {!selectedProgram ? (
            <div className="rounded-2xl border border-dashed border-[#2e2e2e] p-14 text-center">
              <p className="text-sm text-[#3a3a3a]">Create or select a program to begin.</p>
            </div>
          ) : (
            <>
              {activeSection === "dashboard" && <DashboardSection program={selectedProgram} />}
              {activeSection === "program"   && <ProgramSection   program={selectedProgram} authFetch={authFetch} onRefresh={refreshSelectedProgram} onDelete={deleteProgram} setMessage={setMessage} />}
              {activeSection === "scope"     && <ScopeSection     program={selectedProgram} authFetch={authFetch} onRefresh={refreshSelectedProgram} setMessage={setMessage} />}
              {activeSection === "imports"   && <ImportsSection   program={selectedProgram} authFetch={authFetch} onRefresh={refreshSelectedProgram} setMessage={setMessage} />}
              {activeSection === "recon"     && <ReconSection     programId={selectedProgram.id} authFetch={authFetch} setMessage={setMessage} />}
              {activeSection === "scanning"  && <ScanningSection  programId={selectedProgram.id} authFetch={authFetch} setMessage={setMessage} onPromote={promoteScanToFinding} />}
              {activeSection === "manual"    && <ManualSection    program={selectedProgram} authFetch={authFetch} onRefresh={refreshSelectedProgram} setMessage={setMessage} />}
              {activeSection === "findings"  && <FindingsSection  program={selectedProgram} authFetch={authFetch} onRefresh={refreshSelectedProgram} setMessage={setMessage} prefill={findingPrefill} onPrefillConsumed={() => setFindingPrefill(null)} />}
              {activeSection === "reports"   && <ReportsSection   program={selectedProgram} authFetch={authFetch} onRefresh={refreshSelectedProgram} setMessage={setMessage} />}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
