import "@testing-library/jest-dom";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { mockResponse, renderWithApp } from "../../../test-utils/renderWithApp";
import AuthorizationCoveragePanel from "../AuthorizationCoveragePanel";

const base = { scheme: "https", host: "api.example.com", port: null, observed_identities: ["owner"] };
const candidates = { open: 0, promoted: 0, false_positive: 0, backing_evidence: 0 };

const coverage = {
  summary: {
    total: 3, violation_candidate: 1, inconclusive: 0, partial: 0, conclusive: 0, reviewed_not_executed: 1, untested: 1,
  },
  identities: ["owner", "peer", "tenant-b"],
  unmatched_cases: [{ case_id: "c9", name: "elsewhere", reason: "no_observed_operation", request: "GET https://x:443/never/{id}" }],
  operations: [
    {
      ...base, endpoint_id: "e1", method: "GET", path_template: "/orders/{id}", state: "violation_candidate",
      cases: [{ case_id: "c1", name: "orders", test_case_id: "orders", identities: ["owner", "peer"], expected: {}, queued_jobs: 0,
        executed: true, latest_job_id: "j1", assessment_status: "conclusive", reasons: [],
        workflow_review: { setup_count: 1, preflight_identity_ids: ["owner"], captures_declared: true,
          substitutions_observed: true, write_reset_declared: true,
          fixed_profile_blockers: ["setup_capture", "template_substitution"], runner_validation_required: true } }],
      identity_coverage: [
        { identity_id: "owner", state: "evaluated", reason: "reported_allow_or_deny", expected: "allow" },
        { identity_id: "peer", state: "evaluated", reason: "reported_allow_or_deny", expected: "deny" },
        { identity_id: "tenant-b", state: "not_reviewed", reason: "not_in_a_reviewed_case_for_this_operation", expected: null },
      ],
      candidates: { open: 1, promoted: 0, false_positive: 0, backing_evidence: 1 },
    },
    {
      ...base, endpoint_id: "e2", method: "GET", path_template: "/invoices/{id}", state: "reviewed_not_executed",
      cases: [{ case_id: "c2", name: "invoices", test_case_id: "inv", identities: ["owner"], expected: {}, queued_jobs: 1,
        executed: false, latest_job_id: null, assessment_status: null, reasons: [] }],
      identity_coverage: [{ identity_id: "owner", state: "reviewed_not_run", reason: "no_executed_assessment", expected: "allow" }],
      candidates,
    },
    {
      ...base, endpoint_id: "e3", method: "GET", path_template: "/profile", state: "untested", cases: [],
      identity_coverage: [{ identity_id: "owner", state: "not_reviewed", reason: "not_in_a_reviewed_case_for_this_operation", expected: null }],
      candidates,
    },
  ],
};

const emptyCoverage = {
  summary: { total: 0, violation_candidate: 0, inconclusive: 0, partial: 0, conclusive: 0, reviewed_not_executed: 0, stale: 0, untested: 0 },
  operations: [], identities: [], unmatched_cases: [], unattributed_assessments: [], filtered_total: 0,
};

describe("AuthorizationCoveragePanel", () => {
  it("shows each operation's state, candidates and per-identity coverage", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: coverage } },
    });
    expect(await screen.findByText("GET /orders/{id}")).toBeInTheDocument();
    expect(screen.getByText("1 open · 0 promoted · 1 with evidence")).toBeInTheDocument();
    expect(screen.getAllByText("Violation candidate").length).toBeGreaterThan(0);
    expect(screen.getByText("tenant-b · not reviewed")).toBeInTheDocument();
    expect(screen.getByText("owner · reviewed, not run")).toBeInTheDocument();
    expect(screen.getAllByText(/1 reviewed case$/).length).toBe(2);
    await userEvent.click(screen.getByText(/orders: workflow prerequisites/));
    expect(screen.getByText(/Setup\/reset capture is outside the controlled fixed-request profile/)).toBeInTheDocument();
    expect(screen.getByText(/Write reset is not end-of-case cleanup/)).toBeInTheDocument();
  });

  it("never presents a conclusive result as a security statement", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: coverage } },
    });
    expect(await screen.findByText(/does not mean the operation is secure/)).toBeInTheDocument();
  });

  it("shows the HTTP outcome, reported decision and proof with the individual assessment state", async () => {
    const item = {
      ...coverage.operations[0].cases[0], baseline_valid: true, identity_results: {
        peer: { state: "evaluated", reason: "state_unchanged", expected: "deny", observed: "allow",
          reported_decision: "denied", source: "write_verification", write_verification: "verified_no_effect" },
      },
    };
    const body = { ...coverage, operations: [{ ...coverage.operations[0], cases: [item] }] };
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body } },
    });
    await userEvent.click(await screen.findByText("orders · assessment details"));
    expect(screen.getByText("Legitimate baseline valid")).toBeVisible();
    expect(screen.getByText("Expected deny · Raw HTTP outcome allow")).toBeVisible();
    expect(screen.getByText("Reported decision denied")).toBeVisible();
    expect(screen.getByText("Decision source write_verification")).toBeVisible();
    expect(screen.getByText("Write verification verified_no_effect")).toBeVisible();
  });

  it("explains the missing proof on a historical HTTP-only result", async () => {
    const operation = coverage.operations[0];
    const peer = { state: "inconclusive", reason: "semantic_assessment_missing", expected: "deny",
      observed: "allow", reported_decision: null, source: null, write_verification: null };
    const item = { ...operation.cases[0], identity_results: { peer } };
    const body = { ...coverage, operations: [{ ...operation, cases: [item] }] };
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body } },
    });
    await userEvent.click(await screen.findByText("orders · assessment details"));
    expect(screen.getByText("Required semantic proof is missing.")).toBeVisible();
    expect(screen.getByText("Expected deny · Raw HTTP outcome allow")).toBeVisible();
    expect(screen.getByText("Reported decision not recorded")).toBeVisible();
  });

  it("filters by state through the backend and marks the active filter", async () => {
    const filtered = { ...coverage, operations: [coverage.operations[2]] };
    const { authFetch } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: coverage },
        "GET /engagements/eng-1/api/coverage?limit=500&state=untested": { body: filtered },
      },
    });
    await screen.findByText("GET /orders/{id}");
    await userEvent.click(screen.getByRole("button", { name: /No reviewed test/ }));
    await waitFor(() => expect(screen.queryByText("GET /orders/{id}")).not.toBeInTheDocument());
    expect(screen.getByText("GET /profile")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /No reviewed test/ })).toHaveAttribute("aria-pressed", "true");
    expect(authFetch).toHaveBeenCalledWith("/engagements/eng-1/api/coverage?limit=500&state=untested");
  });

  it("lists stored cases that were not counted, with the reason", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: coverage } },
    });
    expect(await screen.findByText(/1 stored case not counted as coverage/)).toBeInTheDocument();
    expect(screen.getByText(/its request matches no observed operation/)).toBeInTheDocument();
  });

  it("shows an unmatched reviewed case before any operations are captured", async () => {
    const body = { ...emptyCoverage, unmatched_cases: coverage.unmatched_cases };
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body } },
    });
    await userEvent.click(await screen.findByText(/1 stored case not counted as coverage/));
    expect(screen.getByText("elsewhere")).toBeVisible();
    expect(screen.getByText(/its request matches no observed operation/)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows an unattributed assessment even without cases or captured operations", async () => {
    const assessment = { job_id: "job-8412", case_id: null, assessment_status: "inconclusive", reason: "no_usable_snapshot" };
    const body = { ...emptyCoverage, unattributed_assessments: [assessment] };
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body } },
    });
    await userEvent.click(await screen.findByText(/1 unattributed assessment/i));
    expect(screen.getByText(/job-8412/)).toBeVisible();
    expect(screen.getByText(/no usable request snapshot/i)).toHaveTextContent(/inconclusive/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders nothing without captured operations, unmatched cases, or unattributed assessments", async () => {
    const { container } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: emptyCoverage } },
    });
    await waitFor(() => expect(screen.queryByText("Computing coverage…")).not.toBeInTheDocument());
    expect(container.textContent).not.toContain("Authorization coverage");
  });

  it("tolerates a backend that returns an empty body", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {});
    await waitFor(() => expect(screen.queryByText("Computing coverage…")).not.toBeInTheDocument());
  });
});

describe("AuthorizationCoveragePanel drafting", () => {
  it("offers a draft only where an identity has not been evaluated, passing every engagement identity", async () => {
    const onDraft = jest.fn();
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" onDraft={onDraft} />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: coverage } },
    });
    await screen.findByText("GET /orders/{id}");
    // All three fixture operations have an identity that is not evaluated.
    expect(screen.getAllByRole("button", { name: /Draft a test for/ })).toHaveLength(3);
    await userEvent.click(screen.getByRole("button", { name: "Draft a test for GET /orders/{id}" }));
    expect(onDraft).toHaveBeenCalledWith("e1", ["owner", "peer", "tenant-b"]);
  });

  it("offers no draft when every identity already has an evaluated result", async () => {
    const complete = {
      ...coverage,
      summary: { ...coverage.summary, total: 1 },
      operations: [{
        ...coverage.operations[0],
        identity_coverage: [
          { identity_id: "owner", state: "evaluated", reason: "reported_allow_or_deny", expected: "allow" },
          { identity_id: "peer", state: "evaluated", reason: "reported_allow_or_deny", expected: "deny" },
        ],
      }],
    };
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" onDraft={jest.fn()} />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: complete } },
    });
    await screen.findByText("GET /orders/{id}");
    expect(screen.queryByRole("button", { name: /Draft a test for/ })).not.toBeInTheDocument();
  });
});

describe("AuthorizationCoveragePanel priority", () => {
  const withReasons = {
    ...coverage,
    operations: coverage.operations.map((op, i) => ({
      ...op,
      priority_reasons: i === 0 ? [{ code: "object_identifier_in_path", detail: "The route addresses an object by identifier (object-level access)." }] : [],
    })),
  };

  it("explains why an operation may matter using the reasons the backend captured", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: withReasons } },
    });
    expect(await screen.findByText(/addresses an object by identifier/)).toBeInTheDocument();
  });

  it("requests the backend's priority order when asked", async () => {
    const { authFetch } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: withReasons },
        "GET /engagements/eng-1/api/coverage?limit=500&sort=priority": { body: withReasons },
      },
    });
    await screen.findByText("GET /orders/{id}");
    await userEvent.click(screen.getByRole("checkbox", { name: /Look here first/ }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith("/engagements/eng-1/api/coverage?limit=500&sort=priority"));
  });
});

describe("AuthorizationCoveragePanel pagination", () => {
  const url = "/engagements/eng-1/api/coverage?limit=500";
  const filteredUrl = `${url}&state=untested`;
  const sortedUrl = `${filteredUrl}&sort=priority`;
  const untested = Array.from({ length: 501 }, (_, index) => ({
    ...coverage.operations[2], endpoint_id: `op-${index + 1}`, path_template: `/operation-${index + 1}`,
  }));
  const summary = { ...emptyCoverage.summary, total: 502, untested: 501, violation_candidate: 1 };
  const first = { ...coverage, summary, filtered_total: 501, operations: untested.slice(0, 500) };
  const last = { ...first, operations: untested.slice(500) };
  const routes = {
    [url]: { body: { ...first, filtered_total: 502, operations: [coverage.operations[0], ...untested.slice(0, 499)] } },
    [filteredUrl]: { body: first },
    [`${filteredUrl}&offset=500`]: { body: last },
    [sortedUrl]: { body: first },
    [`${sortedUrl}&offset=500`]: { body: last },
  };

  it("reaches operation 501 and returns with the same state filter and priority order", async () => {
    const { authFetch, container } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        ...routes,
        // Select the controls with a small fixture. Both visits to the sorted first page render all 500 operations.
        [url]: { body: coverage },
        [filteredUrl]: { body: { ...coverage, filtered_total: 1, operations: [coverage.operations[2]] } },
      },
    });
    const filter = await screen.findByRole("button", { name: /No reviewed test/ });
    const priority = screen.getByRole("checkbox", { name: /Look here first/ });
    const status = screen.getByRole("status");
    // Read the rendered table once per response instead of querying every element for each path.
    function expectPage(firstOperation: number, lastOperation: number) {
      const rows = container.querySelector("tbody")!.rows;
      const paths = Array.from(rows, row => row.cells[0].firstElementChild?.textContent);
      expect(paths).toEqual(untested.slice(firstOperation - 1, lastOperation).map(op => `GET ${op.path_template}`));
      expect(rows[rows.length - 1].cells[0]).toBeVisible();
    }
    await userEvent.click(filter);
    await userEvent.click(priority);
    expectPage(1, 500);
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(status).toHaveTextContent("501–501 of 501 operations"));
    expectPage(501, 501);
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await waitFor(() => expect(status).toHaveTextContent("1–500 of 501 operations"));
    expectPage(1, 500);
    expect(filter).toHaveAttribute("aria-pressed", "true");
    expect(priority).toBeChecked();
    expect(authFetch.mock.calls.map(([path]) => path)).toEqual([
      url, filteredUrl, sortedUrl, `${sortedUrl}&offset=500`, sortedUrl,
    ]);
  }, 15_000); // Rendering both full pages can exceed the default deadline on a shared CPU.

  it.each(["filter", "sort"])("returns to the first page when the %s changes", async (control) => {
    const { authFetch } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, { routes });
    const filter = await screen.findByRole("button", { name: /No reviewed test/ });
    await userEvent.click(filter);
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("GET /operation-501")).toBeVisible();
    if (control === "filter") {
      await userEvent.click(screen.getByRole("button", { name: /No reviewed test/ }));
      expect(await screen.findByText("GET /orders/{id}")).toBeVisible();
      expect(authFetch).toHaveBeenLastCalledWith(url);
    } else {
      await userEvent.click(screen.getByRole("checkbox", { name: /Look here first/ }));
      expect(await screen.findByText("GET /operation-1")).toBeVisible();
      expect(authFetch).toHaveBeenLastCalledWith(sortedUrl);
    }
    expect(screen.queryByText("GET /operation-501")).not.toBeInTheDocument();
  });

  it("keeps keyboard focus on the status while the next page loads and announces its range", async () => {
    const { authFetch } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { [url]: { body: { ...first, operations: [untested[0]] } } },
    });
    const next = await screen.findByRole("button", { name: "Next page" });
    let finishPage!: (response: Response) => void;
    authFetch.mockReturnValueOnce(new Promise<Response>((resolve) => { finishPage = resolve; }));

    next.focus();
    await userEvent.keyboard("{Enter}");
    expect(authFetch).toHaveBeenLastCalledWith(`${url}&offset=500`);
    const status = screen.getByRole("status");
    expect(status).toHaveFocus();

    await act(async () => { finishPage(mockResponse({ body: last })); });
    expect(screen.getByRole("status")).toBe(status);
    expect(status).toHaveTextContent(/501–501 of 501 operations/);
    expect(status).toHaveFocus();
  });

  it("can return to the first page after the second page fails to load", async () => {
    const { authFetch } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        [url]: { body: { ...first, operations: [untested[0]] } },
        [`${url}&offset=500`]: { ok: false, status: 500 },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Next page" }));
    const previous = await screen.findByRole("button", { name: "Previous page" });
    expect(previous).toBeEnabled();
    await userEvent.click(previous);
    expect(await screen.findByText("GET /operation-1")).toBeVisible();
    expect(authFetch.mock.calls.map(([path]) => path)).toEqual([url, `${url}&offset=500`, url]);
  });

  it("reloads page one when a legacy summary shrinks past the requested offset", async () => {
    const legacy = { ...coverage, summary: { ...emptyCoverage.summary, total: 1, untested: 1 } };
    const { authFetch } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { [url]: { body: { ...coverage, summary, operations: [untested[0]] } } },
    });
    const next = await screen.findByRole("button", { name: "Next page" });
    authFetch.mockResolvedValueOnce(mockResponse({ body: { ...legacy, operations: [] } }))
      .mockResolvedValueOnce(mockResponse({ body: { ...legacy, operations: [coverage.operations[2]] } }));
    await userEvent.click(next);
    expect(await screen.findByText("GET /profile")).toBeVisible();
    expect(screen.queryByText("GET /operation-1")).not.toBeInTheDocument();
    expect(authFetch.mock.calls.map(([path]) => path)).toEqual([url, `${url}&offset=500`, url]);
  });
});

describe("AuthorizationCoveragePanel evidence", () => {
  const reference = {
    evidence_id: "ev-1", job_id: "job-12345678", case_id: "c1", identity_id: "peer",
    content_hash: "abc123", expected: "deny", observed: "allow", reported_decision: "allowed",
    source: "write_verification", write_verification: "verified_effect",
  };
  const withEvidence = {
    ...coverage,
    operations: [{ ...coverage.operations[0], candidate_evidence: [reference] }, ...coverage.operations.slice(1).map((op) => ({ ...op, candidate_evidence: [] }))],
  };
  const path = "/engagements/eng-1/evidence/ev-1";
  const url = `GET ${path}`;

  it("loads the exact cited record on request", async () => {
    const { authFetch } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: withEvidence },
        [url]: { body: { id: "ev-1", body: '{"status_code": 204, "identity_id": "peer"}', content_hash: "abc123" } },
      },
    });
    expect(await screen.findByText("Reported decision allowed")).toBeInTheDocument();
    expect(authFetch).not.toHaveBeenCalledWith(path);
    await userEvent.click(screen.getByRole("button", { name: "View redacted record" }));
    expect(await screen.findByText(/"status_code": 204/)).toBeInTheDocument();
    expect(authFetch).toHaveBeenCalledWith(path);
    expect(screen.getByText(/sha256 abc123 \(matches\)/)).toBeInTheDocument();
  });

  it("flags a record whose hash differs from the coverage reference", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: withEvidence },
        [url]: { body: { id: "ev-1", body: "uncited content", content_hash: "different" } },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "View redacted record" }));
    expect(await screen.findByText(/differs from the coverage reference/)).toBeInTheDocument();
    expect(screen.queryByText("uncited content")).not.toBeInTheDocument();
  });

  it("reports an unavailable reference without falling back to another row", async () => {
    const { authFetch } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: withEvidence },
        [url]: { ok: false, status: 404 },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "View redacted record" }));
    expect(await screen.findByText("The cited evidence is unavailable.")).toBeInTheDocument();
    expect(authFetch.mock.calls.filter(([path]) => path.includes("/evidence"))).toEqual([[path]]);
  });

  it("rejects a different record even when its hash matches", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: withEvidence },
        [url]: { body: { id: "ev-2", body: "uncited content", content_hash: "abc123" } },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "View redacted record" }));
    expect(await screen.findByText(/returned evidence ID differs/)).toBeInTheDocument();
    expect(screen.queryByText("uncited content")).not.toBeInTheDocument();
  });
});

describe("AuthorizationCoveragePanel integrity", () => {
  const stale = {
    ...coverage,
    summary: { ...coverage.summary, total: 2, stale: 1, violation_candidate: 1, reviewed_not_executed: 0, untested: 0 },
    operations: [
      {
        ...coverage.operations[0], endpoint_id: "e5", method: "GET", path_template: "/invoices/{id}", state: "stale",
        cases: [{ case_id: "c5", name: "invoices", test_case_id: "inv", identities: ["owner", "peer"], expected: {}, queued_jobs: 0,
          executed: false, stale_runs: 1, latest_job_id: null, assessment_status: null, reasons: [] }],
        identity_coverage: [
          { identity_id: "owner", state: "reviewed_not_run", reason: "case_changed_since_last_run", expected: null },
          { identity_id: "peer", state: "mixed", reason: "evaluated_in_some_cases_only", expected: "deny" },
        ],
        candidates: { open: 0, promoted: 0, false_positive: 0, backing_evidence: 0 }, candidate_evidence: [], historical_assessments: [],
      },
      {
        ...coverage.operations[0], endpoint_id: "e6", method: "GET", path_template: "/orders/{id}", state: "violation_candidate", cases: [],
        identity_coverage: [], candidate_evidence: [],
        candidates: { open: 1, promoted: 0, false_positive: 0, backing_evidence: 0 },
        historical_assessments: [{ job_id: "job-abcdef12", case_id: "c1", case_name: "orders", reason: "case_modified",
          assessment_status: "conclusive", completed_at: "2026-10-27T00:00:00", candidates: { open: 1, promoted: 0, false_positive: 0 } }],
      },
    ],
  };

  it("labels a case changed since its last run and an identity evaluated in only some cases", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: stale } },
    });
    expect((await screen.findAllByText("Case changed since last run")).length).toBeGreaterThan(0);
    expect(screen.getByText("peer · evaluated in some cases only")).toBeInTheDocument();
    expect(screen.getByText("owner · reviewed, not run")).toBeInTheDocument();
  });

  it("keeps earlier assessments visible but says they are not current coverage, with unresolved candidates", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: stale } },
    });
    expect(await screen.findByText(/1 earlier assessment not counted as current coverage/)).toBeInTheDocument();
    expect(screen.getByText(/the case was edited after this run/)).toBeInTheDocument();
    expect(screen.getByText(/1 open candidate still unresolved/)).toBeInTheDocument();
  });
});
