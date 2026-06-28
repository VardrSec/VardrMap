export type ScopeItem = { id: string; value: string; kind: string; notes: string };
export type ImportRecord = { id: string; tool_type: string; filename: string; imported_count: number };
export type ReconItem = {
  id: string; source: string; url?: string; path?: string; host?: string;
  title?: string; status_code?: number; webserver?: string; port?: string | number;
  tech?: string | string[]; length?: number; words?: number; lines?: number;
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
  services_count: number;
  my_role?: "owner" | "member" | "viewer";
};
export type ApiKey = { id: string; label: string; scope: "full" | "runner"; created_at: string | null; last_used_at: string | null };
export type ProgramMember = { id: string; program_id: string; member_github_id: string; role: string; invited_at: string | null };
export type Service = {
  id: string; program_id: string; host: string; port: number; protocol: string;
  service_name: string; product: string; version: string; state: string; source: string;
  created_at: string | null; last_scanned_at: string | null;
};
export type RadarProgram = {
  id: string; platform: string; platform_id: string; name: string; url: string;
  max_payout: number | null; is_new: boolean;
  discovered_at: string | null; last_fetched_at: string | null;
};
export type SubmissionPrefill = { title: string; report_id: string; finding_id: string };
export type ManualTestFormState = {
  title: string; hypothesis: string; payload: string; evidence: string; status: string;
};
export type ScanJob = {
  id: string; program_id: string; tool_type: string; target_source: string;
  config: Record<string, unknown>; status: string;
  created_at: string | null; started_at: string | null; completed_at: string | null;
  error_message: string;
};

export type LogLine = {
  kind: "sys" | "info" | "out" | "ok" | "warn" | "err" | "hit";
  text: string;
  sev?: string;
};

export type ConfigField = {
  key: string;
  label: string;
  type: "toggle" | "text" | "number";
  default?: boolean;
  placeholder?: string;
};

export type ToolDef = {
  id: string;
  label: string;
  glyph: string;
  blurb: string;
  yields: string;
  yieldsTo: string;
  sources: string[];
  config: ConfigField[];
};

export type ScanJobUI = {
  id: string;
  tool: string;
  source: string;
  config: Record<string, unknown>;
  status: "pending" | "running" | "done" | "failed";
  targets: number;
  progress: number;
  yield: number;
  yieldKind: string;
  queuedAt: string;
  startedAt: string | null;
  endedAt: string | null;
  durationMs: number | null;
  error?: string;
  log: LogLine[];
  _full?: LogLine[];
};
export type JobEvent = {
  id: string;
  job_id: string;
  kind: string;
  text: string;
  created_at: string;
};

export type RunnerInfo = {
  online: boolean;
  last_seen: string | null;
  hostname: string | null;
  version: string | null;
  os: string | null;
  tools: Record<string, { ok: boolean; version: string | null }>;
};
// Top-level fields mirror the most recently seen runner (backward compat);
// `runners` lists every machine that has sent a heartbeat.
export type RunnerStatus = RunnerInfo & { runners?: RunnerInfo[] };
export type ScheduledScan = {
  id: string; program_id: string; tool_type: string; target_source: string;
  config: Record<string, unknown>; interval: string; enabled: boolean;
  last_run_at: string | null; next_run_at: string | null; created_at: string | null;
};
export type UserSettings = { webhook_url: string; notify_min_severity: string };
export type Submission = {
  id: string; program_id: string;
  finding_id: string; report_id: string;
  platform: string; platform_reference: string;
  title: string; status: string; severity: string;
  payout_usd: number | null; notes: string;
  submitted_at: string | null; resolved_at: string | null; created_at: string | null;
};
export type Section = "dashboard" | "scope" | "overview" | "review" | "findings" | "reports" | "submissions" | "settings";
export type AppSession = {
  user?: { name?: string | null; email?: string | null; image?: string | null; githubId?: string; username?: string };
  backendToken?: string;
};
export type AuthFetch = (path: string, init?: RequestInit) => Promise<Response>;
export type FindingFormState = { title: string; severity: string; asset: string; status: string; summary: string; steps: string; impact: string; remediation: string };
export type ReportFormState = { finding_id: string; title: string; summary: string; steps: string; impact: string; remediation: string; cwe: string; cvss: string; status: string };
