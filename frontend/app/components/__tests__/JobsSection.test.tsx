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
  [`GET /engagements/${PROGRAM_ID}/scan-profiles`]: { body: { profiles: [] } },
  [`GET /engagements/${PROGRAM_ID}/test-cases`]: { body: { test_cases: [] } },
};

const STORED_CASE = {
  id: "tc-1", program_id: PROGRAM_ID, name: "BOLA — user profile",
  test_case_id: "bola-check", description: "", spec: {},
  created_at: null, updated_at: null,
};

/** Routes with one stored VardrGate case, for the API Assessment flows. */
const ROUTES_WITH_CASE = {
  ...BASE_ROUTES,
  [`GET /engagements/${PROGRAM_ID}/test-cases`]: { body: { test_cases: [STORED_CASE] } },
  [`POST /engagements/${PROGRAM_ID}/pipelines`]: { body: { jobs: [] } },
  [`POST /engagements/${PROGRAM_ID}/jobs`]: { body: { id: "job-vg", tool_type: "vardrgate_api_test", target_source: "scope", config: {}, status: "pending", created_at: new Date().toISOString(), started_at: null, completed_at: null, error_message: null } },
};

/** Open the collapsed tool list, if it is not already open (prefs persist between tests). */
async function openTools() {
  const toggle = await screen.findByRole("button", { name: /^Tools/ });
  if (toggle.getAttribute("aria-expanded") !== "true") await userEvent.click(toggle);
}

const NEW_JOB = {
  id: "job-1", tool_type: "nuclei", target_source: "scope",
  config: {}, status: "pending", created_at: new Date().toISOString(),
  started_at: null, completed_at: null, error_message: null,
};

describe("JobsSection", () => {
  it("fetches jobs, runner status and recon count on mount, and no schedules", async () => {
    const { authFetch } = renderWithApp(
      <JobsSection engagementId={PROGRAM_ID} />,
      { routes: BASE_ROUTES },
    );

    await waitFor(() => {
      expect(authFetch).toHaveBeenCalledWith(`/engagements/${PROGRAM_ID}/jobs`);
      expect(authFetch).toHaveBeenCalledWith("/runner/status");
      expect(authFetch).toHaveBeenCalledWith(`/engagements/${PROGRAM_ID}/recon?limit=1`);
    });
    expect(authFetch).not.toHaveBeenCalledWith(`/engagements/${PROGRAM_ID}/schedules`);
  });

  it("renders the Composer panel", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: BASE_ROUTES });
    expect(await screen.findByText("Queue a Job")).toBeInTheDocument();
  });

  it("selecting a pipeline does not queue anything on its own", async () => {
    const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
      routes: {
        ...BASE_ROUTES,
        [`POST /engagements/${PROGRAM_ID}/pipelines`]: { body: { jobs: [] } },
      },
    });

    await screen.findByText("Queue a Job");
    await userEvent.click(await screen.findByRole("button", { name: "Select Attack Surface" }));

    expect(authFetch).not.toHaveBeenCalledWith(
      `/engagements/${PROGRAM_ID}/pipelines`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("queues the Attack Surface chain via POST /pipelines once confirmed", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    try {
      const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
        routes: {
          ...BASE_ROUTES,
          [`POST /engagements/${PROGRAM_ID}/pipelines`]: { body: { jobs: [] } },
        },
      });

      await screen.findByText("Queue a Job");
      await userEvent.click(await screen.findByRole("button", { name: "Select Attack Surface" }));
      await userEvent.click(await screen.findByRole("button", { name: "Queue Pipeline" }));

      await waitFor(() =>
        expect(authFetch).toHaveBeenCalledWith(
          `/engagements/${PROGRAM_ID}/pipelines`,
          expect.objectContaining({ method: "POST" }),
        ),
      );
      const call = authFetch.mock.calls.find((c: unknown[]) => c[0] === `/engagements/${PROGRAM_ID}/pipelines`);
      const stages = JSON.parse((call![1] as { body: string }).body).stages;
      expect(stages.map((s: { tool_type: string }) => s.tool_type)).toEqual(["subfinder", "dnsx", "httpx", "nuclei"]);
    } finally {
      confirmSpy.mockRestore();
    }
  });

  it("cancelling the confirm queues nothing", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);
    try {
      const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
        routes: {
          ...BASE_ROUTES,
          [`POST /engagements/${PROGRAM_ID}/pipelines`]: { body: { jobs: [] } },
        },
      });

      await screen.findByText("Queue a Job");
      await userEvent.click(await screen.findByRole("button", { name: "Select Attack Surface" }));
      await userEvent.click(await screen.findByRole("button", { name: "Queue Pipeline" }));

      expect(confirmSpy).toHaveBeenCalled();
      expect(authFetch).not.toHaveBeenCalledWith(
        `/engagements/${PROGRAM_ID}/pipelines`,
        expect.objectContaining({ method: "POST" }),
      );
    } finally {
      confirmSpy.mockRestore();
    }
  });

  it("excluding a stage posts only the included ones, still chained", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    try {
      const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
        routes: {
          ...BASE_ROUTES,
          [`POST /engagements/${PROGRAM_ID}/pipelines`]: { body: { jobs: [] } },
        },
      });

      await screen.findByText("Queue a Job");
      await userEvent.click(await screen.findByRole("button", { name: "Select Attack Surface" }));
      // Drop the middle stage — the survivors must still be posted in order.
      await userEvent.click(screen.getByRole("button", { name: "Exclude httpx" }));
      await userEvent.click(screen.getByRole("button", { name: "Queue Pipeline" }));

      await waitFor(() =>
        expect(authFetch).toHaveBeenCalledWith(
          `/engagements/${PROGRAM_ID}/pipelines`,
          expect.objectContaining({ method: "POST" }),
        ),
      );
      const call = authFetch.mock.calls.find((c: unknown[]) => c[0] === `/engagements/${PROGRAM_ID}/pipelines`);
      const stages = JSON.parse((call![1] as { body: string }).body).stages;
      expect(stages.map((s: { tool_type: string }) => s.tool_type)).toEqual(["subfinder", "dnsx", "nuclei"]);
    } finally {
      confirmSpy.mockRestore();
    }
  });

  it("excluding every stage disables Queue Pipeline", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: BASE_ROUTES });

    await screen.findByText("Queue a Job");
    await userEvent.click(await screen.findByRole("button", { name: "Select Attack Surface" }));
    for (const tool of ["subfinder", "dnsx", "httpx", "nuclei"]) {
      await userEvent.click(screen.getByRole("button", { name: `Exclude ${tool}` }));
    }

    expect(screen.getByRole("button", { name: "Queue Pipeline" })).toBeDisabled();
    expect(screen.getByText("include at least one stage to queue")).toBeInTheDocument();
  });

  it("re-including a stage restores it to its original position", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    try {
      const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
        routes: {
          ...BASE_ROUTES,
          [`POST /engagements/${PROGRAM_ID}/pipelines`]: { body: { jobs: [] } },
        },
      });

      await screen.findByText("Queue a Job");
      await userEvent.click(await screen.findByRole("button", { name: "Select Attack Surface" }));
      await userEvent.click(screen.getByRole("button", { name: "Exclude subfinder" }));
      await userEvent.click(screen.getByRole("button", { name: "Include subfinder" }));
      await userEvent.click(screen.getByRole("button", { name: "Queue Pipeline" }));

      await waitFor(() =>
        expect(authFetch).toHaveBeenCalledWith(
          `/engagements/${PROGRAM_ID}/pipelines`,
          expect.objectContaining({ method: "POST" }),
        ),
      );
      const call = authFetch.mock.calls.find((c: unknown[]) => c[0] === `/engagements/${PROGRAM_ID}/pipelines`);
      const stages = JSON.parse((call![1] as { body: string }).body).stages;
      expect(stages.map((s: { tool_type: string }) => s.tool_type)).toEqual(["subfinder", "dnsx", "httpx", "nuclei"]);
    } finally {
      confirmSpy.mockRestore();
    }
  });

  it("stage exclusions are scoped per pipeline", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    try {
      const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
        routes: {
          ...BASE_ROUTES,
          [`POST /engagements/${PROGRAM_ID}/pipelines`]: { body: { jobs: [] } },
        },
      });

      await screen.findByText("Queue a Job");
      // httpx appears in both chains — excluding it from one must not touch the other.
      await userEvent.click(await screen.findByRole("button", { name: "Select Attack Surface" }));
      await userEvent.click(screen.getByRole("button", { name: "Exclude httpx" }));

      await userEvent.click(screen.getByRole("button", { name: "Select Host Enumeration" }));
      await userEvent.click(screen.getByRole("button", { name: "Queue Pipeline" }));

      await waitFor(() =>
        expect(authFetch).toHaveBeenCalledWith(
          `/engagements/${PROGRAM_ID}/pipelines`,
          expect.objectContaining({ method: "POST" }),
        ),
      );
      const call = authFetch.mock.calls.find((c: unknown[]) => c[0] === `/engagements/${PROGRAM_ID}/pipelines`);
      const stages = JSON.parse((call![1] as { body: string }).body).stages;
      expect(stages.map((s: { tool_type: string }) => s.tool_type)).toEqual(["naabu", "nmap", "httpx"]);
    } finally {
      confirmSpy.mockRestore();
    }
  });

  it("API Assessment cannot be queued until a test case is chosen", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: ROUTES_WITH_CASE });

    await screen.findByText("Queue a Job");
    await userEvent.click(await screen.findByRole("button", { name: "Select API Assessment" }));

    // A vardrgate job without a case is a guaranteed 400 — block it here.
    expect(screen.getByRole("button", { name: "Queue Pipeline" })).toBeDisabled();

    await userEvent.selectOptions(
      await screen.findByRole("combobox", { name: "Authorization test case" }), "tc-1",
    );
    expect(screen.getByRole("button", { name: "Queue Pipeline" })).toBeEnabled();
  });

  it("API Assessment posts the chosen case on the vardrgate stage", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    try {
      const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
        routes: ROUTES_WITH_CASE,
      });

      await screen.findByText("Queue a Job");
      await userEvent.click(await screen.findByRole("button", { name: "Select API Assessment" }));
      await userEvent.selectOptions(
        await screen.findByRole("combobox", { name: "Authorization test case" }), "tc-1",
      );
      await userEvent.click(screen.getByRole("button", { name: "Queue Pipeline" }));

      await waitFor(() =>
        expect(authFetch).toHaveBeenCalledWith(
          `/engagements/${PROGRAM_ID}/pipelines`,
          expect.objectContaining({ method: "POST" }),
        ),
      );
      const call = authFetch.mock.calls.find((c: unknown[]) => c[0] === `/engagements/${PROGRAM_ID}/pipelines`);
      const stages = JSON.parse((call![1] as { body: string }).body).stages;
      expect(stages.map((s: { tool_type: string }) => s.tool_type)).toEqual(["httpx", "vardrgate_api_test"]);
      // The reference must ride on the vardrgate stage, not the httpx one.
      expect(stages[1].config.test_case_id).toBe("tc-1");
      expect(stages[0].config.test_case_id).toBeUndefined();
    } finally {
      confirmSpy.mockRestore();
    }
  });

  it("excluding the vardrgate stage drops the test case requirement", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: ROUTES_WITH_CASE });

    await screen.findByText("Queue a Job");
    await userEvent.click(await screen.findByRole("button", { name: "Select API Assessment" }));
    expect(screen.getByRole("button", { name: "Queue Pipeline" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Exclude vardrgate_api_test" }));
    // httpx alone needs no case.
    expect(screen.getByRole("button", { name: "Queue Pipeline" })).toBeEnabled();
  });

  it("the standalone vardrgate tool offers the picker and posts the reference", async () => {
    const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
      routes: ROUTES_WITH_CASE,
    });

    await screen.findByText("Queue a Job");
    await openTools();
    await userEvent.click(await screen.findByRole("button", { name: "Select vardrgate" }));
    expect(screen.getByRole("button", { name: "Queue Job" })).toBeDisabled();

    await userEvent.selectOptions(
      await screen.findByRole("combobox", { name: "Authorization test case" }), "tc-1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Queue Job" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(
        `/engagements/${PROGRAM_ID}/jobs`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    // /jobs is also fetched on mount, so match the POST specifically.
    const call = authFetch.mock.calls.find(
      (c: unknown[]) =>
        c[0] === `/engagements/${PROGRAM_ID}/jobs` &&
        (c[1] as { method?: string } | undefined)?.method === "POST",
    );
    const sent = JSON.parse((call![1] as { body: string }).body);
    expect(sent.tool_type).toBe("vardrgate_api_test");
    expect(sent.config).toEqual({ test_case_id: "tc-1" });
  });

  it("with no stored cases the picker explains why vardrgate cannot run", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: BASE_ROUTES });

    await screen.findByText("Queue a Job");
    await openTools();
    await userEvent.click(await screen.findByRole("button", { name: "Select vardrgate" }));

    expect(screen.getByText(/no test cases stored/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Queue Job" })).toBeDisabled();
  });

  it("selecting a tool clears the pipeline selection", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: BASE_ROUTES });

    await screen.findByText("Queue a Job");
    const pipeline = await screen.findByRole("button", { name: "Select Attack Surface" });
    await userEvent.click(pipeline);
    expect(pipeline).toHaveAttribute("aria-pressed", "true");

    await openTools();
    const subfinder = screen.getByRole("button", { name: "Select subfinder" });
    await userEvent.click(subfinder);
    expect(pipeline).toHaveAttribute("aria-pressed", "false");
    // Picking closes the list; the chosen tool is what remains.
    expect(screen.getByRole("button", { name: "Select subfinder" })).toHaveAttribute("aria-pressed", "true");
    // Back to a single-tool queue, not a pipeline queue.
    expect(screen.getByRole("button", { name: "Queue Job" })).toBeInTheDocument();
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

  it("offers no recurrence: jobs run once, when the operator runs them", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: BASE_ROUTES });
    await screen.findByText("Queue a Job");
    expect(screen.queryByRole("button", { name: "daily" })).not.toBeInTheDocument();
    expect(screen.queryByText("Recurrence")).not.toBeInTheDocument();
    expect(screen.getByText(/Queued jobs run when you run/)).toBeInTheDocument();
  });

  it("sends the request rate and custom headers with a queued job", async () => {
    const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
      routes: { ...BASE_ROUTES, [`POST /engagements/${PROGRAM_ID}/jobs`]: { body: NEW_JOB } },
    });
    await screen.findByText("Queue a Job");
    await userEvent.type(screen.getByLabelText("Requests per second"), "25");
    await userEvent.type(screen.getByLabelText("Custom headers"), "X-Bug-Bounty: me{enter}X-Test: 1");
    await userEvent.click(screen.getByRole("button", { name: "Queue Job" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(`/engagements/${PROGRAM_ID}/jobs`, expect.objectContaining({ method: "POST" })),
    );
    const call = authFetch.mock.calls.find(
      (c: unknown[]) => c[0] === `/engagements/${PROGRAM_ID}/jobs` && (c[1] as { method?: string })?.method === "POST",
    );
    const { config } = JSON.parse((call![1] as { body: string }).body);
    expect(config.rate).toBe(25);
    expect(config.headers).toEqual({ "X-Bug-Bounty": "me", "X-Test": "1" });
  });

  it("will not queue an invalid header or a rate above the engagement ceiling", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
      routes: BASE_ROUTES,
      overrides: {
        selectedEngagement: { id: PROGRAM_ID, name: "Acme", max_request_rate: 10, scope: { in: [], out: [] } } as never,
      },
    });
    await screen.findByText("Queue a Job");
    const rate = screen.getByLabelText("Requests per second");
    expect(rate).toHaveAttribute("placeholder", "requests/sec (engagement max 10)");

    await userEvent.type(rate, "50");
    expect(screen.getByText("rate exceeds this engagement's ceiling of 10/s")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Queue Job" })).toBeDisabled();

    await userEvent.clear(rate);
    await userEvent.type(screen.getByLabelText("Custom headers"), "no colon here");
    expect(screen.getByText('"no colon here" must be Name: value')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Queue Job" })).toBeDisabled();
  });

  it("applies headers only to the pipeline stages that accept them", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    try {
      const { authFetch } = renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, {
        routes: { ...BASE_ROUTES, [`POST /engagements/${PROGRAM_ID}/pipelines`]: { body: { jobs: [] } } },
      });
      await screen.findByText("Queue a Job");
      await userEvent.click(await screen.findByRole("button", { name: "Select Attack Surface" }));
      await userEvent.type(screen.getByLabelText("Custom headers"), "X-Bug-Bounty: me");
      await userEvent.click(screen.getByRole("button", { name: "Queue Pipeline" }));

      await waitFor(() =>
        expect(authFetch).toHaveBeenCalledWith(`/engagements/${PROGRAM_ID}/pipelines`, expect.objectContaining({ method: "POST" })),
      );
      const call = authFetch.mock.calls.find((c: unknown[]) => c[0] === `/engagements/${PROGRAM_ID}/pipelines`);
      const stages: { tool_type: string; config: Record<string, unknown> }[] =
        JSON.parse((call![1] as { body: string }).body).stages;
      const withHeaders = stages.filter((st) => st.config.headers).map((st) => st.tool_type);
      expect(withHeaders).toEqual(["httpx", "nuclei"]);
    } finally {
      confirmSpy.mockRestore();
    }
  });
  it("collapses the tool list to the chosen tool, and picking from it closes it again", async () => {
    renderWithApp(<JobsSection engagementId={PROGRAM_ID} />, { routes: BASE_ROUTES });
    await screen.findByText("Queue a Job");
    const toggle = screen.getByRole("button", { name: /^Tools/ });
    if (toggle.getAttribute("aria-expanded") === "true") await userEvent.click(toggle);

    // Collapsed: only the selected tool, so its settings are in view.
    expect(screen.getByRole("button", { name: "Select nuclei" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select httpx" })).not.toBeInTheDocument();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByRole("button", { name: "Select httpx" }));

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Select httpx" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Select nuclei" })).not.toBeInTheDocument();
    // Pipelines are untouched by the collapse.
    expect(screen.getByRole("button", { name: "Select Content Discovery" })).toBeInTheDocument();
  });
});
