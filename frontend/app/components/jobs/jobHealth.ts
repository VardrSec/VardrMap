import type { ScanJobUI } from "../../types";

// Elapsed time is a reason to inspect, not proof that a Runner is offline or a
// scan has stopped. No job status, backend state, or execution policy is changed.
export const RUNNING_REVIEW_AFTER_MS = 60 * 60 * 1000;

export function runningJobNeedsReview(
  job: Pick<ScanJobUI, "status" | "startedAt">,
  nowMs: number,
): boolean {
  if (job.status !== "running" || !job.startedAt) return false;
  // Python's naive UTC isoformat timestamps lack Z; browsers otherwise parse
  // them in local time. Explicit offsets and Z remain authoritative.
  const timestamp = job.startedAt.trim();
  if (!timestamp) return false;
  const withZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(timestamp) ? timestamp : `${timestamp}Z`;
  const startedMs = Date.parse(withZone);
  return Number.isFinite(startedMs) && Number.isFinite(nowMs)
    && nowMs - startedMs >= RUNNING_REVIEW_AFTER_MS;
}
