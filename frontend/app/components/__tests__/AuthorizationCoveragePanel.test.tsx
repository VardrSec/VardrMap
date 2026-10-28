import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
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
        executed: true, latest_job_id: "j1", assessment_status: "conclusive", reasons: [] }],
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
  });

  it("never presents a conclusive result as a security statement", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: coverage } },
    });
    expect(await screen.findByText(/does not mean the operation is secure/)).toBeInTheDocument();
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

  it("renders nothing for an engagement with no observed operations", async () => {
    const empty = { operations: [], summary: { total: 0, violation_candidate: 0, inconclusive: 0, partial: 0, conclusive: 0, reviewed_not_executed: 0, untested: 0 }, identities: [], unmatched_cases: [] };
    const { container } = renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: { "GET /engagements/eng-1/api/coverage?limit=500": { body: empty } },
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

describe("AuthorizationCoveragePanel evidence", () => {
  const reference = {
    evidence_id: "ev-1", job_id: "job-12345678", case_id: "c1", identity_id: "peer",
    content_hash: "abc123", expected: "deny", observed: "allow",
  };
  const withEvidence = {
    ...coverage,
    operations: [{ ...coverage.operations[0], candidate_evidence: [reference] }, ...coverage.operations.slice(1).map((op) => ({ ...op, candidate_evidence: [] }))],
  };
  const url = "GET /engagements/eng-1/evidence?job_id=job-12345678&limit=1&case_id=c1&identity_id=peer";

  it("states what was reviewed against what was observed and loads the redacted record on request", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: withEvidence },
        [url]: { body: { evidence: [{ id: "ev-1", body: '{"status_code": 200, "identity_id": "peer"}', content_hash: "abc123" }], total: 1 } },
      },
    });
    expect(await screen.findByText(/was reviewed as/)).toBeInTheDocument();
    expect(screen.queryByText(/status_code/)).not.toBeInTheDocument(); // not fetched until asked
    await userEvent.click(screen.getByRole("button", { name: "View redacted record" }));
    expect(await screen.findByText(/"status_code": 200/)).toBeInTheDocument();
    expect(screen.getByText(/sha256 abc123 \(matches\)/)).toBeInTheDocument();
  });

  it("flags a record whose hash differs from the coverage reference", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: withEvidence },
        [url]: { body: { evidence: [{ id: "ev-1", body: "{}", content_hash: "different" }], total: 1 } },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "View redacted record" }));
    expect(await screen.findByText(/differs from the coverage reference/)).toBeInTheDocument();
  });

  it("says so when the record cannot be loaded", async () => {
    renderWithApp(<AuthorizationCoveragePanel engagementId="eng-1" />, {
      routes: {
        "GET /engagements/eng-1/api/coverage?limit=500": { body: withEvidence },
        [url]: { body: { evidence: [], total: 0 } },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "View redacted record" }));
    expect(await screen.findByText("The record could not be loaded.")).toBeInTheDocument();
  });
});
