import type { PipelineDef, ToolDef } from "../../types";

export const TOOLS: Record<string, ToolDef> = {
  subfinder: {
    id: "subfinder",
    label: "subfinder",
    glyph: "⊹",
    blurb: "Passive subdomain enumeration",
    yields: "subdomains",
    yieldsTo: "recon",
    sources: ["scope"],
    config: [],
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
  nmap: {
    id: "nmap",
    label: "nmap",
    glyph: "◎",
    blurb: "Service & port discovery",
    yields: "services",
    yieldsTo: "services",
    sources: ["scope", "recon"],
    config: [
      { key: "top_ports", label: "Top ports", type: "number", placeholder: "100" },
      { key: "timing", label: "Timing (0-4)", type: "number", placeholder: "3" },
    ],
  },
  dnsx: {
    id: "dnsx",
    label: "dnsx",
    glyph: "⊚",
    blurb: "Resolve hosts, drop dead records",
    yields: "resolvable hosts",
    yieldsTo: "recon",
    sources: ["recon", "scope"],
    config: [
      { key: "limit", label: "Limit", type: "number", placeholder: "500" },
    ],
  },
  naabu: {
    id: "naabu",
    label: "naabu",
    glyph: "◍",
    blurb: "Fast port sweep",
    yields: "open ports",
    yieldsTo: "services",
    sources: ["scope", "recon"],
    config: [
      { key: "top_ports", label: "Top ports", type: "number", placeholder: "100" },
      { key: "limit", label: "Limit", type: "number", placeholder: "500" },
    ],
  },
  katana: {
    id: "katana",
    label: "katana",
    glyph: "◬",
    blurb: "Crawl sites for endpoints",
    yields: "endpoints",
    yieldsTo: "recon",
    sources: ["recon", "scope"],
    config: [
      { key: "depth", label: "Depth", type: "number", placeholder: "3" },
      { key: "limit", label: "Limit", type: "number", placeholder: "100" },
      { key: "js_crawl", label: "Parse JavaScript", type: "toggle", default: false },
    ],
  },
  gau: {
    id: "gau",
    label: "gau",
    glyph: "◷",
    blurb: "Archived URLs from public sources (passive)",
    yields: "archived URLs",
    yieldsTo: "recon",
    // Like subfinder, gau reads the engagement's wildcard scope entries.
    sources: ["scope"],
    config: [
      { key: "subs", label: "Include subdomains", type: "toggle", default: true },
      { key: "providers", label: "Providers", type: "text", placeholder: "wayback,commoncrawl,otx,urlscan" },
    ],
  },
  ffuf: {
    id: "ffuf",
    label: "ffuf",
    glyph: "⊞",
    blurb: "Fuzz site roots for hidden paths (active)",
    yields: "paths",
    yieldsTo: "recon",
    sources: ["recon", "scope"],
    config: [
      // A name, not a path — the runner resolves it against its own wordlists
      // directory, and the API refuses anything path-shaped.
      { key: "wordlist", label: "Wordlist name", type: "text", placeholder: "common" },
      { key: "extensions", label: "Extensions", type: "text", placeholder: ".php,.bak" },
      { key: "match_codes", label: "Status filter", type: "text", placeholder: "200,301,403" },
      // The rate cap bounds the load this puts on a client's host; there is no
      // value that disables it.
      { key: "rate", label: "Requests/sec", type: "number", placeholder: "50" },
    ],
  },
  vardrgate_api_test: {
    id: "vardrgate_api_test",
    label: "vardrgate",
    glyph: "⊗",
    blurb: "API authorization testing (BOLA, BFLA, cross-tenant)",
    yields: "authorization findings",
    yieldsTo: "scan",
    // Self-contained: the request under test travels inside the stored case, so
    // no scope or recon targets are resolved. A source is still required by the
    // API, and "scope" is the honest one — the case belongs to the engagement.
    sources: ["scope"],
    config: [
      { key: "test_case_id", label: "Test case id", type: "text", placeholder: "<stored case>" },
    ],
  },
};

/**
 * The chains the Composer offers, defined once.
 *
 * Stages are individually includable, so each entry is a menu rather than a
 * fixed chain — the Composer posts only the enabled subset and the backend
 * relinks `depends_on` sequentially over whatever it receives. The endpoint
 * accepts any valid ordered chain; these are just what the UI offers.
 *
 * Composer renders from this and JobsSection posts the selection it hands back,
 * so what the operator sees is exactly what gets queued.
 */
export const PIPELINES: PipelineDef[] = [
  {
    id: "attack-surface",
    label: "Attack Surface",
    // Each stage feeds the next through the recon store: subfinder discovers
    // names, dnsx drops the ones that don't resolve, httpx finds what answers,
    // nuclei scans what's live.
    blurb: "Map an unknown external surface, then scan what answers",
    stages: [
      { tool_type: "subfinder", target_source: "scope", config: {} },
      { tool_type: "dnsx", target_source: "recon", config: {} },
      { tool_type: "httpx", target_source: "recon", config: {} },
      { tool_type: "nuclei", target_source: "recon", config: { severity: "high,critical" } },
    ],
  },
  {
    id: "host-enumeration",
    label: "Host Enumeration",
    // For a scope you were given rather than one you discovered. These read the
    // same scope rather than feeding each other; chaining them keeps a pentest
    // from putting three tools on the client's hosts at once.
    blurb: "Sweep ports, identify services, probe what serves HTTP",
    stages: [
      { tool_type: "naabu", target_source: "scope", config: { top_ports: "100" } },
      { tool_type: "nmap", target_source: "scope", config: { top_ports: "100", timing: "3" } },
      { tool_type: "httpx", target_source: "scope", config: {} },
    ],
  },
  {
    id: "content-discovery",
    label: "Content Discovery",
    // subfinder finds names, httpx keeps the live ones, katana crawls those for
    // endpoints, and gau adds URLs public archives already hold for the scope
    // domains. All four land in the recon store.
    blurb: "Find live hosts, crawl them, and pull archived URLs",
    stages: [
      { tool_type: "subfinder", target_source: "scope", config: {} },
      { tool_type: "httpx", target_source: "recon", config: {} },
      { tool_type: "katana", target_source: "recon", config: {} },
      { tool_type: "gau", target_source: "scope", config: {} },
    ],
  },
  {
    id: "api-assessment",
    label: "API Assessment",
    // httpx confirms the API is reachable and fingerprints it; vardrgate then
    // replays the stored test case as each identity. The vardrgate stage needs a
    // test_case_id, so it is excluded until one is chosen — see Composer.
    blurb: "Probe the API, then test its authorization as several identities",
    stages: [
      { tool_type: "httpx", target_source: "scope", config: {} },
      { tool_type: "vardrgate_api_test", target_source: "scope", config: {} },
    ],
  },
];

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
