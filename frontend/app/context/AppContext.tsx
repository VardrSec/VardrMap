"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from "react";
import { AppSession, AuthFetch, EngagementStatus, EngagementType, Finding, Engagement, Report, ScanItem, Section } from "../types";
import { AppAction, AppState, appReducer, initialState } from "./appReducer";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

// Defensively coerce every field so components never have to deal with undefined
// coming from the API — e.g. a missing recon_count just becomes 0.
function normalizeEngagement(raw: unknown): Engagement {
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
    // Engagement context. Defaults match the backend's, so an engagement
    // created before these existed normalises to a bug bounty programme.
    client_id:            String(p.client_id ?? ""),
    engagement_type:      (p.engagement_type as EngagementType) ?? "bug_bounty",
    engagement_status:    (p.engagement_status as EngagementStatus) ?? "active",
    starts_at:            String(p.starts_at ?? ""),
    ends_at:              String(p.ends_at ?? ""),
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
    services_count:       n(p.services_count),
    my_role:              (p.my_role as "owner" | "member" | "viewer" | undefined) ?? "owner",
  };
}

export { normalizeEngagement };

async function getFrontendSession(): Promise<AppSession | null> {
  try {
    const res = await fetch("/api/auth/session", { method: "GET", credentials: "include", cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || Object.keys(data).length === 0) return null;
    return data;
  } catch { return null; }
}

export type AppContextValue = {
  state: AppState;
  selectedEngagement: Engagement | null;
  authFetch: AuthFetch;
  setMessage: (msg: string) => void;
  selectEngagement: (id: string) => void;
  navigate: (section: Section) => void;
  navigateToDashboard: (toolOrAction?: string) => void;
  refreshSelectedEngagement: (engagementId?: string) => Promise<void>;
  loadEngagements: () => Promise<void>;
  deleteEngagement: () => Promise<void>;
  promoteScanToFinding: (scan: ScanItem) => void;
  promoteToReport: (finding: Finding) => void;
  promoteToSubmission: (report: Report) => void;
  dispatch: React.Dispatch<AppAction>;
};

export const AppContext = createContext<AppContextValue | null>(null);

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

  const selectEngagement = useCallback((id: string) => {
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

  const loadEngagements = useCallback(async () => {
    try {
      const res = await authFetch("/engagements");
      if (!res.ok) throw new Error();
      const data = await res.json();
      const engagements = Array.isArray(data?.engagements) ? data.engagements.map(normalizeEngagement) : [];
      dispatch({ type: "ENGAGEMENTS_LOADED", engagements });
    } catch {
      dispatch({ type: "SET_MESSAGE", message: "Failed to load engagements." });
    }
  }, [authFetch]);

  const refreshSelectedEngagement = useCallback(async (engagementId?: string) => {
    const id = engagementId || state.selectedEngagementId;
    if (!id) return;
    try {
      const res = await authFetch(`/engagements/${id}`);
      if (!res.ok) throw new Error();
      dispatch({ type: "ENGAGEMENT_UPDATED", engagement: normalizeEngagement(await res.json()) });
    } catch {
      dispatch({ type: "SET_MESSAGE", message: "Failed to refresh engagement." });
    }
  }, [state.selectedEngagementId, authFetch]);

  const deleteEngagement = useCallback(async () => {
    if (!state.selectedEngagementId || !confirm("Delete this engagement?")) return;
    try {
      const res = await authFetch(`/engagements/${state.selectedEngagementId}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      dispatch({ type: "ENGAGEMENT_DELETED", id: state.selectedEngagementId });
      dispatch({ type: "SET_MESSAGE", message: "Engagement deleted." });
    } catch {
      dispatch({ type: "SET_MESSAGE", message: "Failed to delete engagement." });
    }
  }, [state.selectedEngagementId, authFetch]);

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

  const promoteToSubmission = useCallback((report: Report) => {
    dispatch({
      type: "PROMOTE_TO_SUBMISSION",
      prefill: {
        title: report.title,
        report_id: report.id,
        finding_id: report.finding_id || "",
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

  // Load engagements once auth completes
  useEffect(() => {
    if (!state.authLoading && state.session?.backendToken) {
      void authFetch("/auth/sync", { method: "POST" }).catch(() => {});
      void loadEngagements();
    }
  // syncUser and loadEngagements are stable (empty or auth-token deps) but including
  // them here would re-fire on every context render. Intentional omission.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.authLoading, state.session?.backendToken]);

  const selectedEngagement = useMemo(
    () => state.engagements.find((p) => p.id === state.selectedEngagementId) ?? null,
    [state.engagements, state.selectedEngagementId],
  );

  const value: AppContextValue = {
    state,
    selectedEngagement,
    authFetch,
    setMessage,
    selectEngagement,
    navigate,
    navigateToDashboard,
    refreshSelectedEngagement,
    loadEngagements,
    deleteEngagement,
    promoteScanToFinding,
    promoteToReport,
    promoteToSubmission,
    dispatch,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useAppContext must be used inside AppProvider");
  return ctx;
}
