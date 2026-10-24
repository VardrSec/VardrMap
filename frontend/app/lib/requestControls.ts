// Per-job request rate and custom headers, the two controls a program's testing rules most
// often dictate (a rate limit and an identification header). The rules mirror the backend's
// `_validate_headers` and rate bounds in routers/jobs.py, which mirror VardrRunner, so the
// composer catches a bad value before it is queued instead of after a 400.

/** Tools that take `config.rate` (requests per second). */
export const RATE_TOOLS: readonly string[] = ["httpx", "nuclei", "katana", "ffuf"];
/** Tools that take `config.headers`. */
export const HEADER_TOOLS: readonly string[] = ["httpx", "nuclei", "katana", "ffuf", "dalfox"];

export const RATE_MIN = 1;
export const RATE_MAX = 1000;
const MAX_HEADERS = 20;
const MAX_HEADER_LEN = 2000;
const HEADER_NAME = /^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,100}$/;
const CONTROL_CHAR = /[\x00-\x1f\x7f]/;

export type RequestControls = { rate: string; headers: string };

/** Parse "Name: value" lines. Blank lines are ignored. */
export function parseHeaders(text: string): { headers: Record<string, string>; error: string | null } {
  const headers: Record<string, string> = {};
  const seen = new Set<string>();
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lines.length > MAX_HEADERS) return { headers, error: `at most ${MAX_HEADERS} headers` };
  for (const line of lines) {
    const sep = line.indexOf(":");
    if (sep < 0) return { headers, error: `"${line.trim()}" must be Name: value` };
    const name = line.slice(0, sep).trim();
    const value = line.slice(sep + 1).trim();
    if (!HEADER_NAME.test(name)) return { headers, error: `invalid header name "${name}"` };
    if (CONTROL_CHAR.test(value)) return { headers, error: `header "${name}" has an invalid value` };
    if (name.length + value.length + 2 > MAX_HEADER_LEN) return { headers, error: `header "${name}" is too long` };
    if (seen.has(name.toLowerCase())) return { headers, error: `duplicate header "${name}"` };
    seen.add(name.toLowerCase());
    headers[name] = value;
  }
  return { headers, error: null };
}

export function formatHeaders(raw: unknown): string {
  if (Array.isArray(raw)) return raw.map(String).join("\n");
  if (raw && typeof raw === "object") {
    return Object.entries(raw as Record<string, unknown>).map(([k, v]) => `${k}: ${String(v)}`).join("\n");
  }
  return "";
}

/** Null when the rate is blank (tool default) or valid; otherwise why it is not. */
export function rateError(rate: string, ceiling: number | null): string | null {
  if (rate.trim() === "") return null;
  const n = Number(rate);
  if (!Number.isInteger(n) || n < RATE_MIN || n > RATE_MAX) return `rate must be a whole number from ${RATE_MIN} to ${RATE_MAX}`;
  if (ceiling != null && n > ceiling) return `rate exceeds this engagement's ceiling of ${ceiling}/s`;
  return null;
}

/** The tool's config with the controls applied, only for the tools that accept each key. */
export function withRequestControls(
  toolType: string, config: Record<string, unknown>, controls: RequestControls,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...config };
  delete next.rate;
  delete next.headers;
  if (RATE_TOOLS.includes(toolType) && controls.rate.trim() !== "") next.rate = Number(controls.rate);
  const { headers } = parseHeaders(controls.headers);
  if (HEADER_TOOLS.includes(toolType) && Object.keys(headers).length > 0) next.headers = headers;
  return next;
}
