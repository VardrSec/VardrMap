import type { RunnerInfo, RunnerStatus } from "../types";

export const OBSERVATION_TTL_MS = 60_000;
export type Freshness = "recent" | "stale" | "unknown";
export type Readiness = {
  schema_version: 1;
  component: "vardrmap-api";
  status: "ready" | "not_ready";
  checked_at: string;
  checks: { database: "ok" | "unavailable"; migrations: "current" | "not_current" | "unavailable" | "not_checked" };
};
export type Observation<T> =
  | { kind: "received"; value: T; receivedAt: number }
  | { kind: "unreachable" | "unknown"; receivedAt: number };

const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function timestamp(value: unknown): number {
  // Backend observations are UTC/offset-aware; ambiguous local times are unknown.
  return typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
}

export function observationFreshness(checkedAt: string, receivedAt: number, now: number): Freshness {
  const age = now - timestamp(checkedAt);
  if (!Number.isFinite(age) || age < -5000 || now < receivedAt) return "unknown";
  return Math.max(age, now - receivedAt) >= OBSERVATION_TTL_MS ? "stale" : "recent";
}

export function parseReadiness(value: unknown, status: number): Readiness | null {
  if (!object(value) || !object(value.checks) || value.schema_version !== 1 ||
      value.component !== "vardrmap-api" || !Number.isFinite(timestamp(value.checked_at))) return null;
  const checks = value.checks;
  if (!["ok", "unavailable"].includes(String(checks.database)) ||
      !["current", "not_current", "unavailable", "not_checked"].includes(String(checks.migrations))) return null;
  const ready = checks.database === "ok" && checks.migrations === "current";
  if (ready ? value.status !== "ready" || status !== 200 : value.status !== "not_ready" || status !== 503) return null;
  if (checks.database === "unavailable" && checks.migrations !== "not_checked") return null;
  return value as Readiness;
}

export function parseRunnerStatus(value: unknown): RunnerStatus | null {
  if (!object(value) || value.schema_version !== 1 || !Number.isFinite(timestamp(value.checked_at)) ||
      value.stale_after_seconds !== 300 || !Array.isArray(value.runners)) return null;
  for (const row of value.runners) {
    if (!object(row) || typeof row.online !== "boolean" || !Number.isFinite(timestamp(row.last_seen)) ||
        !["recent", "stale", "unknown"].includes(String(row.freshness)) ||
        ![row.hostname, row.version, row.os].every(v => typeof v === "string") || !object(row.tools)) return null;
    if (!Object.values(row.tools).every(tool => object(tool) && typeof tool.ok === "boolean" &&
        (tool.version == null || typeof tool.version === "string"))) return null;
  }
  const rows = value.runners as RunnerInfo[];
  const recent = rows.some(row => row.online && row.freshness === "recent");
  return {
    ...(rows[0] ?? {last_seen:null, hostname:null, version:null, os:null, tools:{}}),
    online: recent,
    freshness: recent ? "recent" : rows[0]?.freshness ?? "unknown",
    schema_version: 1,
    checked_at: value.checked_at as string,
    stale_after_seconds: 300,
    runners: rows,
  };
}

export function runnerFreshness(runner: RunnerInfo, now: number, staleAfterSeconds = 300): Freshness {
  const age = now - timestamp(runner.last_seen);
  if (!Number.isFinite(age) || age < -5000 || runner.freshness === "unknown") return "unknown";
  const ttl = Number.isFinite(staleAfterSeconds) && staleAfterSeconds > 0 ? Math.min(staleAfterSeconds, 300) : 300;
  if (age >= ttl * 1000 || runner.freshness === "stale") return "stale";
  return runner.online === true ? "recent" : "unknown";
}

export function runnerRecentlySeen(status: RunnerStatus | null, now: number): boolean {
  if (!status || (status.checked_at && observationFreshness(status.checked_at, now, now) !== "recent")) return false;
  if (status.runners != null && !Array.isArray(status.runners)) return false;
  return (status.runners ?? [status]).some(row => row && typeof row === "object" && runnerFreshness(row, now, status.stale_after_seconds) === "recent");
}
