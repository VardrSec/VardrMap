import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import type { ScanJobUI } from "../../../types";
import JobBoard from "../JobBoard";
import { runningJobNeedsReview, RUNNING_REVIEW_AFTER_MS } from "../jobHealth";

const nowMs = Date.parse("2026-10-30T20:00:00Z");
const baseJob: ScanJobUI = {
  id: "job-1", tool: "httpx", source: "scope", config: {},
  status: "running", targets: 1, progress: 50, yield: 0, yieldKind: "live hosts",
  queuedAt: "2026-10-30T17:00:00Z", startedAt: "2026-10-30T18:30:00Z",
  endedAt: null, durationMs: null, log: [],
};

describe("Running-job review hint", () => {
  it("flags only running jobs at or above the elapsed-time threshold", () => {
    expect(runningJobNeedsReview(baseJob, nowMs)).toBe(true);
    expect(runningJobNeedsReview({ ...baseJob, startedAt: new Date(nowMs - RUNNING_REVIEW_AFTER_MS).toISOString() }, nowMs)).toBe(true);
    expect(runningJobNeedsReview({ ...baseJob, startedAt: new Date(nowMs - RUNNING_REVIEW_AFTER_MS + 1).toISOString() }, nowMs)).toBe(false);
    expect(runningJobNeedsReview({ ...baseJob, status: "done" }, nowMs)).toBe(false);
    expect(runningJobNeedsReview({ ...baseJob, status: "failed" }, nowMs)).toBe(false);
    expect(runningJobNeedsReview({ ...baseJob, startedAt: null }, nowMs)).toBe(false);
    expect(runningJobNeedsReview({ ...baseJob, startedAt: "not-a-date" }, nowMs)).toBe(false);
    expect(runningJobNeedsReview({ ...baseJob, startedAt: "2026-10-30T21:00:00Z" }, nowMs)).toBe(false);
  });

  it("treats backend naive ISO timestamps as UTC rather than the browser's timezone", () => {
    expect(runningJobNeedsReview({ ...baseJob, startedAt: "2026-10-30T18:30:00" }, nowMs)).toBe(true);
  });

  it.each(["stream", "pipeline", "table"] as const)(
    "shows an advisory Check Runner hint in the %s view, without changing job status",
    (view) => {
      render(
        <JobBoard jobs={[baseJob]} accent="#f59e0b" nowMs={nowMs} view={view}
          onViewChange={() => {}} activeId={null} onSelect={() => {}}
          onDelete={() => {}} onRunPending={() => {}} pendingCount={0}
        />,
      );
      const hint = screen.getByText("Check Runner", { exact: false });
      expect(hint).toHaveAttribute("title", expect.stringContaining("not proof"));
      expect(screen.queryByText("Failed")).not.toBeInTheDocument();
    },
  );

  it("does not show the hint for a recent running job", () => {
    render(
      <JobBoard jobs={[{ ...baseJob, startedAt: "2026-10-30T19:50:00Z" }]}
        accent="#f59e0b" nowMs={nowMs} view="stream"
        onViewChange={() => {}} activeId={null} onSelect={() => {}}
        onDelete={() => {}} onRunPending={() => {}} pendingCount={0}
      />,
    );
    expect(screen.queryByText(/Check Runner/)).not.toBeInTheDocument();
  });
});
