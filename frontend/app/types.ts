export type ScopeItem = { id: string; value: string; kind: string; notes: string };
export type ImportRecord = { id: string; tool_type: string; filename: string; imported_count: number };
export type ReconItem = {
  id: string; source: string; url?: string; path?: string; host?: string;
  title?: string; status_code?: number; webserver?: string; port?: string | number;
  tech?: string | string[]; length?: number; words?: number; lines?: number;
  content_type?: string; notes?: string; job_id?: string | null;
};
export type ScanItem = {
  id: string; source: string; template_id: string; title: string;
  severity: string; asset: string; matched_at?: string; type?: string;
  description?: string; status: string; cwe?: string; cvss?: string;
  job_id?: string | null;
};
export type ScanProfile = {
  id: string; program_id: string; name: string; tool_type: string;
  target_source: string; config: Record<string, unknown>; created_at: string | null;
};
export type JobPreview = {
  tool_type: string; target_source: string; count: number;
  sample: string[]; truncated: boolean;
};
export type ScanTriageResult = {
  id: string; priority: string; false_positive: boolean; rationale: string;
};
export type ManualTest = { id: string; title: string; hypothesis: string; payload: string; evidence: string; status: string };
export type Finding = { id: string; title: string; severity: string; asset: string; status: string; summary: string; steps: string; impact: string; remediation: string; created_at?: string | null };
/**
 * A report is a client deliverable, so its lifecycle tracks the document's
 * journey to the client — not a bounty platform's verdict on a submission.
 * Mirrors `ReportStatus` in `backend/schemas.py`.
 */
export const REPORT_STATUSES = ["draft", "internal_review", "final", "delivered", "archived"] as const;
export type ReportStatus = (typeof REPORT_STATUSES)[number];

export type Report = { id: string; finding_id: string; title: string; summary: string; steps: string; impact: string; remediation: string; cwe: string; cvss: string; status: ReportStatus; created_at: string };
export type EngagementType = "bug_bounty" | "pentest" | "red_team" | "internal";
export type EngagementStatus = "planned" | "active" | "reporting" | "closed";

export type Client = {
  id: string; name: string; contact_name: string; contact_email: string;
  notes: string; created_at: string;
};

export type Authorization = {
  id: string; program_id: string; permits: string;
  authorized_by: string; authorized_at: string; reference: string;
  window_start: string; window_end: string;
  status: "active" | "expired" | "revoked";
  notes: string; created_at: string;
};

export type Engagement = {
  id: string; name: string; platform: string; program_url: string;
  scope_summary: string; severity_guidance: string; safe_harbor_notes: string;
  // Engagement context. Empty string / defaults for bug bounty work.
  client_id: string;
  engagement_type: EngagementType;
  engagement_status: EngagementStatus;
  starts_at: string;
  ends_at: string;
  /** Organisation the engagement belongs to. Serialized by the backend. */
  org_id?: string;
  /**
   * The operator's own halt switch. Serialized so a client can show the brake is
   * on without having to infer it from a refused request.
   */
  stop_work_at?: string;
  stop_work_reason?: string;
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
export type EngagementMember = { id: string; program_id: string; member_github_id: string; role: string; invited_at: string | null };
export type Service = {
  id: string; program_id: string; host: string; port: number; protocol: string;
  service_name: string; product: string; version: string; state: string; source: string;
  created_at: string | null; last_scanned_at: string | null;
};
export type ApiExchange = {
  id: string; endpoint_id: string; source_tool: string; identity_label: string;
  request_headers: string; request_body: string; response_headers: string; response_body: string;
  request_hash: string; response_hash: string; response_status: number | null;
  response_length: number | null; response_mime: string; response_time_ms: number | null;
  parameter_names: string[]; note: string; captured_at: string | null; created_at: string | null;
};
export type ApiEndpoint = {
  id: string; program_id: string; method: string; scheme: string; host: string;
  port: number | null; path_template: string; source: string; notes: string;
  observation_count: number; statuses: number[]; identities: string[];
  first_seen_at: string | null; last_seen_at: string | null; exchanges?: ApiExchange[];
};
export type RadarProgram = {
  id: string; platform: string; platform_id: string; name: string; url: string;
  max_payout: number | null; is_new: boolean;
  discovered_at: string | null; last_fetched_at: string | null;
};
export type ManualTestFormState = {
  title: string; hypothesis: string; payload: string; evidence: string; status: string;
};
/** An advisory policy finding. The job runs regardless — see docs/security-model.md. */
export type PolicyWarning = { reason: string; message: string };

/** One stage of a chained pipeline. Posted as-is to `POST /engagements/{id}/pipelines`. */
export type PipelineStage = {
  tool_type: string;
  target_source: string;
  config: Record<string, unknown>;
};

/** A stored VardrGate authorization test case. Jobs reference one by `id`. */
export type AuthorizationTestCase = {
  id: string;
  program_id: string;
  name: string;
  /** VardrGate's own spec.id, surfaced for traceability. */
  test_case_id: string;
  description: string;
  spec: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
};

/** A named chain the Composer offers. Stages are individually includable. */
export type PipelineDef = {
  id: string;
  label: string;
  blurb: string;
  stages: PipelineStage[];
};

export type ScanJob = {
  id: string; program_id: string; tool_type: string; target_source: string;
  config: Record<string, unknown>; status: string;
  created_at: string | null; started_at: string | null; completed_at: string | null;
  error_message: string;
  /** Present on create/claim/PATCH-to-running responses; empty when nothing is flagged. */
  warnings?: PolicyWarning[];
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
export type Section = "dashboard" | "scope" | "overview" | "review" | "findings" | "reports" | "settings";
export type AppSession = {
  user?: { name?: string | null; email?: string | null; image?: string | null; githubId?: string; username?: string };
  backendToken?: string;
};
export type AuthFetch = (path: string, init?: RequestInit) => Promise<Response>;
export type FindingFormState = { title: string; severity: string; asset: string; status: string; summary: string; steps: string; impact: string; remediation: string };
export type ReportFormState = { finding_id: string; title: string; summary: string; steps: string; impact: string; remediation: string; cwe: string; cvss: string; status: string };
