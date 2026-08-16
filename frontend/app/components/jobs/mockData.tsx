import type { PipelineStage, ToolDef } from "../../types";

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
};

/**
 * The recon chain offered by the Composer, defined once.
 *
 * Stages are individually includable, so this is the menu rather than a fixed
 * chain — the Composer posts only the enabled subset and the backend relinks
 * `depends_on` sequentially over whatever it receives. The full endpoint accepts
 * any valid ordered chain; this is just what the UI offers.
 *
 * Composer renders from this and JobsSection posts the selection it hands back,
 * so what the operator sees is exactly what gets queued.
 */
export const RECON_PIPELINE: PipelineStage[] = [
  { tool_type: "subfinder", target_source: "scope", config: {} },
  { tool_type: "httpx", target_source: "recon", config: {} },
  { tool_type: "nuclei", target_source: "recon", config: { severity: "high,critical" } },
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
