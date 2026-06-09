import type { LogLine, ScanJobUI, ToolDef } from "../../types";

// ---------------------------------------------------------------------------
// Runner host stub — reflects what vardrrunner status would return
// ---------------------------------------------------------------------------
export const RUNNER = {
  host: "vardr-rig",
  user: "jorge",
  os: "Kali 2026.1 · x86_64",
  version: "v1.2.0",
  concurrency: 2,
  tools: [
    { id: "httpx", version: "1.6.9", ok: true },
    { id: "nuclei", version: "3.3.4", ok: true },
    { id: "subfinder", version: "2.6.6", ok: true },
  ],
};

// Throughput history (jobs completed per ~5-min bucket) for the sparkline
export const THROUGHPUT = [2, 1, 3, 2, 4, 3, 5, 2, 4, 6, 3, 4];

export const TOOLS: Record<string, ToolDef> = {
  subfinder: {
    id: "subfinder",
    label: "subfinder",
    glyph: "⊹",
    blurb: "Passive subdomain enumeration",
    yields: "subdomains",
    yieldsTo: "recon",
    sources: ["scope"],
    config: [
      { key: "recursive", label: "Recursive", type: "toggle", default: true },
      { key: "sources", label: "Sources", type: "text", placeholder: "crtsh,virustotal" },
    ],
  },
  httpx: {
    id: "httpx",
    label: "httpx",
    glyph: "◉",
    blurb: "Probe live hosts & fingerprint",
    yields: "live hosts",
    yieldsTo: "recon",
    sources: ["scope", "recon"],
    config: [
      { key: "status_code", label: "Status filter", type: "text", placeholder: "200,403" },
      { key: "limit", label: "Limit", type: "number", placeholder: "500" },
    ],
  },
  nuclei: {
    id: "nuclei",
    label: "nuclei",
    glyph: "◈",
    blurb: "Template-based vuln scanning",
    yields: "findings",
    yieldsTo: "scan",
    sources: ["recon", "scope"],
    config: [
      { key: "severity", label: "Severity", type: "text", placeholder: "high,critical" },
      { key: "templates", label: "Templates", type: "text", placeholder: "cves,exposures" },
    ],
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _seq = 100;
export function nextId() { return `job_${++_seq}`; }

export function fmtClock(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function fmtAgo(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function fmtDur(ms: number | null): string {
  if (ms == null) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

export function computeYield(tool: string, targets: number): number {
  if (tool === "subfinder") return Math.round(targets * (8 + Math.random() * 4));
  if (tool === "httpx") return Math.round(targets * (0.55 + Math.random() * 0.18));
  return Math.floor(Math.random() * 4);
}

// ---------------------------------------------------------------------------
// Log-stream scripts
// ---------------------------------------------------------------------------

type JobWithSummary = ScanJobUI & {
  summary?: { sev: string; text: string; at: string }[];
};

export function logFor(job: JobWithSummary): LogLine[] {
  const L = (kind: LogLine["kind"], text: string, sev?: string): LogLine => ({ kind, text, sev });

  if (job.tool === "subfinder") {
    return [
      L("sys", `vardrrunner › claimed ${job.id} · subfinder`),
      L("info", `enumerating *.nebulacloud.io from ${job.targets} scope roots`),
      L("out", "sources: crtsh, virustotal, hackertarget, wayback, dnsdumpster"),
      L("out", "[crtsh] 1,204 certificates parsed"),
      L("out", "[wayback] 318 historical hosts"),
      L("ok", "found api.nebulacloud.io"),
      L("ok", "found auth.nebulacloud.io"),
      L("ok", "found grafana.nebulacloud.io"),
      L("ok", "found s3-internal.nebulacloud.io"),
      L("out", "deduplicating + resolving …"),
      L("ok", `${job.yield} unique subdomains resolved`),
      L("sys", `→ pushed ${job.yield} entries to VardrMap · recon`),
    ];
  }

  if (job.tool === "httpx") {
    return [
      L("sys", `vardrrunner › claimed ${job.id} · httpx`),
      L("info", `probing ${job.targets} hosts · threads=50 · follow-redirects`),
      L("ok", "https://api.nebulacloud.io [200] [nginx] [HTTP/2]"),
      L("ok", "https://app.nebulacloud.io [200] [cloudflare] [react]"),
      L("warn", "https://legacy.nebulacloud.io [403] [Apache/2.4.29]"),
      L("ok", "https://ops.nebulacloud.io [200] [Spring Boot]"),
      L("warn", "https://vpn.nebulacloud.io [401] [OpenResty]"),
      L("out", "https://mail.nebulacloud.io [502] timeout"),
      L("ok", "https://grafana.nebulacloud.io [200] [Grafana v9.1.0]"),
      L("out", "fingerprinting tech stacks …"),
      L("ok", `${job.yield} live hosts · ${job.targets - job.yield} filtered`),
      L("sys", `→ pushed ${job.yield} entries to VardrMap · recon`),
    ];
  }

  // nuclei
  const lines: LogLine[] = [
    L("sys", `vardrrunner › claimed ${job.id} · nuclei`),
    L("info", `loading templates: ${(job.config.templates as string) || "cves,exposures"}`),
    L("out", "4,213 templates · 38 protocols loaded"),
    L("info", `scanning ${job.targets} targets · rate=150/s`),
  ];

  if (job.status === "failed" || job.error) {
    lines.push(L("out", "resolving template directory 'misconfiguration' …"));
    lines.push(L("err", "FATAL template dir not found: misconfiguration"));
    lines.push(L("sys", `✗ ${job.id} failed · exit 1`));
    return lines;
  }

  const hits = (job.summary || []).length
    ? job.summary!
    : [
        { sev: "critical", text: "CVE-2024-3094 · xz backdoor", at: "api.nebulacloud.io" },
        { sev: "high", text: "Exposed .git/config", at: "legacy.nebulacloud.io" },
        { sev: "medium", text: "Missing SPF record", at: "mail.nebulacloud.io" },
      ];

  hits.forEach((h) => lines.push(L("hit", `[${h.sev}] ${h.text} → ${h.at}`, h.sev)));
  lines.push(L("ok", `${hits.length} findings · scan complete`));
  lines.push(L("sys", `→ pushed ${hits.length} findings to VardrMap · scan`));
  return lines;
}

// ---------------------------------------------------------------------------
// Seed jobs — computed lazily to avoid stale SSR timestamps
// ---------------------------------------------------------------------------

function makeSeedJobs(): JobWithSummary[] {
  const minsAgo = (m: number) => new Date(Date.now() - m * 60000).toISOString();
  const secsAgo = (s: number) => new Date(Date.now() - s * 1000).toISOString();

  return [
    {
      id: "job_091", tool: "nuclei", source: "recon", status: "done",
      config: { severity: "high,critical", templates: "cves,exposures" },
      targets: 89, progress: 100, yield: 3, yieldKind: "findings",
      queuedAt: minsAgo(48), startedAt: minsAgo(46), endedAt: minsAgo(41),
      durationMs: 5 * 60000 + 12000, log: [],
      summary: [
        { sev: "critical", text: "CVE-2024-3094 · xz backdoor signature", at: "api.nebulacloud.io" },
        { sev: "high", text: "Exposed .git/config", at: "legacy.nebulacloud.io" },
        { sev: "high", text: "Spring Boot actuator /env exposed", at: "ops.nebulacloud.io" },
      ],
    },
    {
      id: "job_092", tool: "httpx", source: "scope", status: "done",
      config: { status_code: "200,403", limit: "500" },
      targets: 142, progress: 100, yield: 89, yieldKind: "live hosts",
      queuedAt: minsAgo(55), startedAt: minsAgo(54), endedAt: minsAgo(52),
      durationMs: 2 * 60000 + 4000, log: [],
    },
    {
      id: "job_093", tool: "subfinder", source: "scope", status: "done",
      config: { recursive: true },
      targets: 14, progress: 100, yield: 142, yieldKind: "subdomains",
      queuedAt: minsAgo(60), startedAt: minsAgo(59), endedAt: minsAgo(56),
      durationMs: 3 * 60000, log: [],
    },
    {
      id: "job_094", tool: "nuclei", source: "scope", status: "failed",
      config: { templates: "misconfiguration" },
      targets: 14, progress: 38, yield: 0, yieldKind: "findings",
      queuedAt: minsAgo(20), startedAt: minsAgo(19), endedAt: minsAgo(18),
      durationMs: 47000, error: "template dir not found: misconfiguration (try a built-in tag)",
      log: [],
    },
    {
      id: "job_095", tool: "httpx", source: "recon", status: "running",
      config: { status_code: "200", limit: "1000" },
      targets: 142, progress: 41, yield: 0, yieldKind: "live hosts",
      queuedAt: minsAgo(3), startedAt: secsAgo(70), endedAt: null,
      durationMs: null, log: [],
    },
    {
      id: "job_096", tool: "nuclei", source: "recon", status: "pending",
      config: { severity: "medium,high,critical", templates: "cves,exposures,takeovers" },
      targets: 89, progress: 0, yield: 0, yieldKind: "findings",
      queuedAt: secsAgo(40), startedAt: null, endedAt: null, durationMs: null, log: [],
    },
    {
      id: "job_097", tool: "subfinder", source: "scope", status: "pending",
      config: { recursive: true, sources: "crtsh,virustotal" },
      targets: 14, progress: 0, yield: 0, yieldKind: "subdomains",
      queuedAt: secsAgo(15), startedAt: null, endedAt: null, durationMs: null, log: [],
    },
  ];
}

export function initJobs(): ScanJobUI[] {
  return makeSeedJobs().map((s) => {
    const j = { ...s };
    if (j.status === "running" && !j.yield) j.yield = computeYield(j.tool, j.targets);
    const full = logFor(j);
    let log: LogLine[] = [];
    if (j.status === "done" || j.status === "failed") {
      log = full;
    } else if (j.status === "running") {
      log = full.slice(0, Math.max(1, Math.floor((j.progress / 100) * full.length)));
    }
    const { summary: _s, ...rest } = j;
    void _s;
    return { ...rest, _full: full, log };
  });
}
