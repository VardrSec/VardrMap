export type ScopeItem = { id: string; value: string; kind: string; notes: string };
export type ImportRecord = { id: string; tool_type: string; filename: string; imported_count: number };
export type ReconItem = {
  id: string; source: string; url?: string; path?: string; host?: string;
  title?: string; status_code?: number; webserver?: string; port?: string | number;
  tech?: string[]; length?: number; words?: number; lines?: number;
  content_type?: string; notes?: string;
};
export type ScanItem = {
  id: string; source: string; template_id: string; title: string;
  severity: string; asset: string; matched_at?: string; type?: string;
  description?: string; status: string; cwe?: string; cvss?: string;
};
export type ManualTest = { id: string; title: string; hypothesis: string; payload: string; evidence: string; status: string };
export type Finding = { id: string; title: string; severity: string; asset: string; status: string; summary: string; steps: string; impact: string; remediation: string; created_at?: string | null };
export type Report = { id: string; finding_id: string; title: string; summary: string; steps: string; impact: string; remediation: string; cwe: string; cvss: string; status: string };
export type Program = {
  id: string; name: string; platform: string; program_url: string;
  scope_summary: string; severity_guidance: string; safe_harbor_notes: string;
  scope: { in: ScopeItem[]; out: ScopeItem[] };
  imports: ImportRecord[];
  recon_count: number;
  scans_count: number;
  manual_tests_count: number;
  findings_count: number;
  findings_by_severity: Record<string, number>;
  findings_by_status: Record<string, number>;
  reports_count: number;
};
export type Section = "dashboard" | "program" | "scope" | "imports" | "recon" | "scanning" | "manual" | "findings" | "reports";
export type AppSession = {
  user?: { name?: string | null; email?: string | null; image?: string | null; githubId?: string; username?: string };
  backendToken?: string;
};
export type AuthFetch = (path: string, init?: RequestInit) => Promise<Response>;
export type FindingFormState = { title: string; severity: string; asset: string; status: string; summary: string; steps: string; impact: string; remediation: string };
export type ReportFormState = { finding_id: string; title: string; summary: string; steps: string; impact: string; remediation: string; cwe: string; cvss: string; status: string };
