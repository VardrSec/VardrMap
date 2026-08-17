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
