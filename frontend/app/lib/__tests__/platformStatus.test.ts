import { observationFreshness, parseReadiness, parseRunnerStatus, runnerFreshness, runnerRecentlySeen } from "../platformStatus";
import type { RunnerInfo } from "../../types";

const now = Date.parse("2026-10-26T12:00:00Z");
const ready = { schema_version:1, component:"vardrmap-api", status:"ready", checked_at:new Date(now).toISOString(), checks:{database:"ok", migrations:"current"} };
const runner: RunnerInfo = {online:true, freshness:"recent", last_seen:new Date(now - 299000).toISOString(), hostname:"laptop", version:"1.0", os:"Linux", tools:{}};

it("accepts explicit 503 unready state and refuses inconsistent/unsupported readiness", () => {
  expect(parseReadiness(ready, 200)).not.toBeNull();
  expect(parseReadiness({...ready, status:"not_ready", checks:{database:"unavailable", migrations:"not_checked"}}, 503)).not.toBeNull();
  expect(parseReadiness(ready, 503)).toBeNull();
  expect(parseReadiness({...ready, schema_version:2}, 200)).toBeNull();
  expect(parseReadiness({...ready, checked_at:"2026-10-26T12:00:00"}, 200)).toBeNull();
  expect(parseReadiness({...ready, checks:{database:"ok", migrations:"not_current"}}, 200)).toBeNull();
});

it("ages a successful observation even without another poll and fails closed on clock uncertainty", () => {
  expect(observationFreshness(ready.checked_at, now, now + 59999)).toBe("recent");
  expect(observationFreshness(ready.checked_at, now, now + 60000)).toBe("stale");
  expect(observationFreshness("invalid", now, now)).toBe("unknown");
  expect(observationFreshness(new Date(now + 10000).toISOString(), now, now)).toBe("unknown");
});

it("expires Runner contact at five minutes, ignores an old online flag and treats missing/future timestamps as unknown", () => {
  expect(runnerFreshness(runner, now)).toBe("recent");
  expect(runnerFreshness(runner, now + 1000)).toBe("stale");
  expect(runnerFreshness({...runner, last_seen:null}, now)).toBe("unknown");
  expect(runnerFreshness({...runner, last_seen:new Date(now + 10000).toISOString()}, now)).toBe("unknown");
  expect(runnerFreshness({...runner, freshness:"unknown"}, now)).toBe("unknown");
});

it("requires a supported report shape and ages cached Jobs bridge reports", () => {
  const report = {...runner, runners:[runner], schema_version:1, checked_at:ready.checked_at, stale_after_seconds:300};
  expect(parseRunnerStatus(report)).not.toBeNull();
  expect(parseRunnerStatus({...report, schema_version:2})).toBeNull();
  expect(parseRunnerStatus({...report, runners:[{...runner, tools:{httpx:{ok:"true"}}}]})).toBeNull();
  expect(runnerRecentlySeen(report, now)).toBe(true);
  expect(runnerRecentlySeen({...report, checked_at:new Date(now + 1000).toISOString()}, now)).toBe(true);
  expect(runnerRecentlySeen(report, now + 1000)).toBe(false);
  expect(runnerRecentlySeen({...report, runners:[{...runner, last_seen:new Date(now).toISOString()}]}, now + 60000)).toBe(false);
  expect(runnerRecentlySeen(null, now)).toBe(false);
});
