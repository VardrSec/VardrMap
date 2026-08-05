import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));
// Bridge calls Object.entries on runnerStatus.tools before the first fetch resolves.
// Mock it to a stable stub so tests focus on JobsSection's data / queue logic.
jest.mock("../jobs/Bridge", () => ({ __esModule: true, default: () => <div data-testid="bridge-stub" /> }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import JobsSection from "../JobsSection";

const PROGRAM_ID = "prog-1";

const BASE_ROUTES = {
  [`GET /engagements/${PROGRAM_ID}/jobs`]: { body: { jobs: [] } },
  "GET /runner/status": { body: { online: false } },
  [`GET /engagements/${PROGRAM_ID}/recon?limit=1`]: { body: { total: 0 } },
  [`GET /engagements/${PROGRAM_ID}/schedules`]: { body: { schedules: [] } },
};

const NEW_JOB = {
  id: "job-1", tool_type: "nuclei", target_source: "scope",
  config: {}, status: "pending", created_at: new Date().toISOString(),
  started_at: null, completed_at: null, error_message: null,
};

describe("JobsSection", () => {
  it("fetches jobs, runner status, recon count, and schedules on mount", async () => {
    const { authFetch } = renderWithApp(
      <JobsSection engagementId={PROGRAM_ID} />,
      { routes: BASE_ROUTES },
    );

    await waitFor(() => {
      expect(authFetch).toHaveBeenCalledWith(`/engagements/${PROGRAM_ID}/jobs`);
      expect(authFetch).toHaveBeenCalledWith("/runner/status");
      expect(authFetch).toHaveBeenCalledWith(`/engagements/${PROGRAM_ID}/recon?limit=1`);
      expect(authFetch).toHaveBeenCalledWith(`/engagements/${PROGRAM_ID}/schedules`);
    });
  });

  it("renders the Composer panel", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: BASE_ROUTES });
    expect(await screen.findByText("Queue a Job")).toBeInTheDocument();
  });

  it("queues a one-time job via POST /jobs when Queue Job is clicked", async () => {
    const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
      routes: {
        ...BASE_ROUTES,
        [`POST /engagements/${PROGRAM_ID}/jobs`]: { body: NEW_JOB },
      },
    });

    await screen.findByText("Queue a Job");
    await userEvent.click(await screen.findByRole("button", { name: "Queue Job" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(
        `/engagements/${PROGRAM_ID}/jobs`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("creates a schedule via POST /schedules when a recurrence is picked", async () => {
    const SCHEDULE = {
      id: "sched-1", tool_type: "subfinder", target_source: "scope",
      config: {}, interval: "daily", enabled: true,
      next_run_at: null, last_run_at: null, created_at: new Date().toISOString(),
    };
    const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
      routes: {
        ...BASE_ROUTES,
        [`POST /engagements/${PROGRAM_ID}/schedules`]: { body: SCHEDULE },
      },
    });

    await screen.findByText("Queue a Job");

    // Switch to subfinder — accessible name includes glyph + label + blurb
    await userEvent.click(await screen.findByRole("button", { name: /subfinder/i }));

    // Select daily recurrence
    await userEvent.click(await screen.findByRole("button", { name: "daily" }));

    // Submit button now reads "Schedule daily"
    await userEvent.click(await screen.findByRole("button", { name: "Schedule daily" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(
        `/engagements/${PROGRAM_ID}/schedules`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
