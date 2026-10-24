import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import Bridge from "../Bridge";
import type { RunnerStatus } from "../../../types";

const STATUS: RunnerStatus = {
  online: true, last_seen: new Date().toISOString(), hostname: "laptop", version: "0.48.0", os: "Windows",
  tools: {},
};

function renderBridge(overrides: Partial<Parameters<typeof Bridge>[0]> = {}) {
  render(
    <Bridge
      accent="#f59e0b" runnerOnline runnerStatus={STATUS} lastPoll={new Date().toISOString()}
      queueDepth={0} runningCount={0} busy={false} pulseKey={0} collapsed={false}
      onRefreshRunner={() => {}} onToggleCollapse={() => {}} onSetupRunner={() => {}}
      {...overrides}
    />,
  );
}

describe("Bridge", () => {
  it("shows the runner's version beside its name", () => {
    renderBridge();
    expect(screen.getByText("v0.48.0")).toHaveClass("text-[10px]");
    expect(screen.getByText("v0.48.0").parentElement).toHaveTextContent("VardrRunnerv0.48.0");
  });

  it("keeps the last reported version while the runner is offline, and in the collapsed strip", () => {
    renderBridge({ runnerOnline: false, collapsed: true });
    expect(screen.getByText("v0.48.0")).toBeInTheDocument();
  });

  it("has no auto-run toggle", () => {
    renderBridge();
    expect(screen.queryByText(/auto-run/i)).not.toBeInTheDocument();
  });
});
