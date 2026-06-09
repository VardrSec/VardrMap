"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from "react";
import { AppSession, AuthFetch, Finding, Program, ScanItem, Section } from "../types";
import { AppAction, AppState, appReducer, initialState } from "./appReducer";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

// Defensively coerce every field so components never have to deal with undefined
// coming from the API — e.g. a missing recon_count just becomes 0.
function normalizeProgram(raw: unknown): Program {
  const p = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const scope = p.scope && typeof p.scope === "object" ? p.scope as Record<string, unknown> : {};
  const n = (v: unknown) => (typeof v === "number" ? v : 0);
  const asRecord = (v: unknown): Record<string, number> =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, val]) => [k, n(val)]))
      : {};
  return {
    id:                   String(p.id ?? ""),
    name:                 String(p.name ?? ""),
    platform:             String(p.platform ?? ""),
    program_url:          String(p.program_url ?? ""),
    scope_summary:        String(p.scope_summary ?? ""),
    severity_guidance:    String(p.severity_guidance ?? ""),
    safe_harbor_notes:    String(p.safe_harbor_notes ?? ""),
    scope: {
      in:  Array.isArray(scope.in)  ? scope.in  : [],
      out: Array.isArray(scope.out) ? scope.out : [],
    },
    imports:              Array.isArray(p.imports) ? p.imports : [],
    recon_count:          n(p.recon_count),
    scans_count:          n(p.scans_count),
    manual_tests_count:   n(p.manual_tests_count),
    findings_count:       n(p.findings_count),
    findings_by_severity: asRecord(p.findings_by_severity),
    findings_by_status:   asRecord(p.findings_by_status),
    reports_count:        n(p.reports_count),
  };
}

export { normalizeProgram };

async function getFrontendSession(): Promise<AppSession | null> {
  try {
    const res = await fetch("/api/auth/session", { method: "GET", credentials: "include", cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || Object.keys(data).length === 0) return null;
    return data;
  } catch { return null; }
}

type AppContextValue = {
  state: AppState;
  selectedProgram: Program | null;
  authFetch: AuthFetch;
  setMessage: (msg: string) => void;
  selectProgram: (id: string) => void;
  navigate: (section: Section) => void;
  navigateToDashboard: (toolOrAction?: string) => void;
  refreshSelectedProgram: (programId?: string) => Promise<void>;
  loadPrograms: () => Promise<void>;
  deleteProgram: () => Promise<void>;
  promoteScanToFinding: (scan: ScanItem) => void;
  promoteToReport: (finding: Finding) => void;
  dispatch: React.Dispatch<AppAction>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialState);

  // authFetch reads the session via a ref so it never needs to be re-created
  // when the session changes — child useEffect dep arrays stay stable.
  const sessionRef = useRef(state.session);
  useEffect(() => { sessionRef.current = state.session; }, [state.session]);

  // Auto-clear toast after 4 s
  useEffect(() => {
    if (!state.message) return;
    const id = setTimeout(() => dispatch({ type: "CLEAR_MESSAGE" }), 4000);
    return () => clearTimeout(id);
  }, [state.message]);

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
      dispatch({ type: "SET_MESSAGE", message: "Session expired. Please sign in again." });
      throw new Error("Unauthorized");
    }
    return response;
  }, []);

  const setMessage = useCallback((msg: string) => {
    dispatch({ type: "SET_MESSAGE", message: msg });
  }, []);

  const selectProgram = useCallback((id: string) => {
    dispatch({ type: "PROGRAM_SELECT", id });
  }, []);

  const navigate = useCallback((section: Section) => {
    dispatch({ type: "NAVIGATE", section });
  }, []);

  const navigateToDashboard = useCallback((toolOrAction?: string) => {
    if (toolOrAction === "import") {
      dispatch({ type: "NAVIGATE_TO_DASHBOARD", tab: "import" });
    } else {
      dispatch({ type: "NAVIGATE_TO_DASHBOARD", tool: toolOrAction });
    }
  }, []);

  const loadPrograms = useCallback(async () => {
    try {
      const res = await authFetch("/programs");
      if (!res.ok) throw new Error();
      const data = await res.json();
      const programs = Array.isArray(data?.programs) ? data.programs.map(normalizeProgram) : [];
      dispatch({ type: "PROGRAMS_LOADED", programs });
    } catch {
      dispatch({ type: "SET_MESSAGE", message: "Failed to load programs." });
    }
  }, [authFetch]);

  const refreshSelectedProgram = useCallback(async (programId?: string) => {
    const id = programId || state.selectedProgramId;
    if (!id) return;
    try {
      const res = await authFetch(`/programs/${id}`);
      if (!res.ok) throw new Error();
      dispatch({ type: "PROGRAM_UPDATED", program: normalizeProgram(await res.json()) });
    } catch {
      dispatch({ type: "SET_MESSAGE", message: "Failed to refresh program." });
    }
  }, [state.selectedProgramId, authFetch]);

  const deleteProgram = useCallback(async () => {
    if (!state.selectedProgramId || !confirm("Delete this program?")) return;
    try {
      const res = await authFetch(`/programs/${state.selectedProgramId}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      dispatch({ type: "PROGRAM_DELETED", id: state.selectedProgramId });
      dispatch({ type: "SET_MESSAGE", message: "Program deleted." });
    } catch {
      dispatch({ type: "SET_MESSAGE", message: "Failed to delete program." });
    }
  }, [state.selectedProgramId, authFetch]);

  const promoteScanToFinding = useCallback((scan: ScanItem) => {
    dispatch({
      type: "PROMOTE_TO_FINDING",
      prefill: {
        title: scan.title,
        severity: scan.severity || "medium",
        asset: scan.asset || "",
        status: "candidate",
        summary: scan.description || "",
        steps: "",
        impact: "",
        remediation: "",
      },
    });
  }, []);

  const promoteToReport = useCallback((finding: Finding) => {
    dispatch({
      type: "PROMOTE_TO_REPORT",
      prefill: {
        finding_id: finding.id,
        title: finding.title,
        summary: finding.summary || "",
        steps: finding.steps || "",
        impact: finding.impact || "",
        remediation: finding.remediation || "",
        cwe: "",
        cvss: "",
        status: "draft",
      },
    });
  }, []);

  // Bootstrap auth on mount
  useEffect(() => {
    void (async () => {
      const session = await getFrontendSession();
      dispatch({ type: "AUTH_LOADED", session });
    })();
  }, []);

  // Load programs once auth completes
  useEffect(() => {
    if (!state.authLoading && state.session?.backendToken) {
      void authFetch("/auth/sync", { method: "POST" }).catch(() => {});
      void loadPrograms();
    }
  // syncUser and loadPrograms are stable (empty or auth-token deps) but including
  // them here would re-fire on every context render. Intentional omission.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.authLoading, state.session?.backendToken]);

  const selectedProgram = useMemo(
    () => state.programs.find((p) => p.id === state.selectedProgramId) ?? null,
    [state.programs, state.selectedProgramId],
  );

  const value: AppContextValue = {
    state,
    selectedProgram,
    authFetch,
    setMessage,
    selectProgram,
    navigate,
    navigateToDashboard,
    refreshSelectedProgram,
    loadPrograms,
    deleteProgram,
    promoteScanToFinding,
    promoteToReport,
    dispatch,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useAppContext must be used inside AppProvider");
  return ctx;
}
