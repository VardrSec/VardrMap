import type { ToolDef } from "../../types";

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
 * The canonical recon chain, defined once.
 *
 * Composer renders these stages and JobsSection posts them, so what the operator
 * is shown is exactly what gets queued. Each stage waits on the previous one via
 * `depends_on`; the backend accepts any valid ordered chain, this is just the
 * one the UI offers.
 */
export const RECON_PIPELINE = [
  { tool_type: "subfinder", target_source: "scope", config: {} as Record<string, unknown> },
  { tool_type: "httpx", target_source: "recon", config: {} as Record<string, unknown> },
  { tool_type: "nuclei", target_source: "recon", config: { severity: "high,critical" } },
] as const;

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
