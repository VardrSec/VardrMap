import "@testing-library/jest-dom";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import AuthorizationCaseBuilder from "../AuthorizationCaseBuilder";
import EngagementDeliverables from "../EngagementDeliverables";
import FindingActivityPanel from "../FindingActivityPanel";
import type { Engagement } from "../../types";

const PROGRAM: Engagement = {
  id: "prog-1", name: "Test Engagement", platform: "", program_url: "",
  scope_summary: "", severity_guidance: "", safe_harbor_notes: "",
  client_id: "", engagement_type: "pentest", engagement_status: "active",
  starts_at: "", ends_at: "",
  scope: { in: [], out: [] }, imports: [],
  recon_count: 0, scans_count: 0, manual_tests_count: 0,
  findings_count: 0, findings_by_severity: {}, findings_by_status: {}, reports_count: 0,
  services_count: 0,
};
const VIEWER: Engagement = { ...PROGRAM, my_role: "viewer" };

type Authfetch = jest.Mock<Promise<Response>, [string, RequestInit?]>;

/** The single call a component made with this method and path, with its JSON body parsed. */
function sent(authFetch: Authfetch, method: string, path: string) {
  const calls = authFetch.mock.calls.filter(([p, init]) => p === path && (init?.method ?? "GET") === method);
  return { count: calls.length, body: calls[0]?.[1]?.body ? JSON.parse(String(calls[0][1]?.body)) : undefined };
}

// ── FindingActivityPanel ────────────────────────────────────────────────────

describe("FindingActivityPanel", () => {
  const ACTIVITY = "/engagements/prog-1/findings/f1/activity";
  const LOAD = `${ACTIVITY}?limit=50&offset=0`;
  const EVIDENCE = "/engagements/prog-1/evidence?finding_id=f1&limit=50&offset=0";
  const ENTRY = {
    id: "a1", kind: "retest", outcome: "verified_fixed", notes: "Re-ran the exploit; it is blocked.",
    actor: "gh_user1", created_at: "2026-10-09T01:00:00Z", snapshot: { title: "SQLi" },
    evidence: [{ id: "e1", title: "Retest output", content_hash: "ab12cd" }],
  };
  const routes = {
    [`GET ${LOAD}`]: { body: { activities: [ENTRY], total: 1 } },
    [`GET ${EVIDENCE}`]: { body: { evidence: [], total: 0 } },
  };
  const open = () => userEvent.click(screen.getByText(/Remediation & retests/));

  it("loads nothing until the panel is opened", async () => {
    const { authFetch } = renderWithApp(<FindingActivityPanel engagementId="prog-1" findingId="f1" readOnly={false} />, { routes });
    expect(authFetch).not.toHaveBeenCalled();
    await open();
    expect(await screen.findByText(/Re-ran the exploit/)).toBeInTheDocument();
  });

  it("shows the timeline entry with its outcome and the evidence hash it was based on", async () => {
    renderWithApp(<FindingActivityPanel engagementId="prog-1" findingId="f1" readOnly={false} />, { routes });
    await open();
    expect(await screen.findByText(/retest verified fixed/)).toBeInTheDocument();
    expect(screen.getByText(/SHA-256 ab12cd/)).toBeInTheDocument();
  });

  it("is read-only for viewers: the timeline shows but there is no form", async () => {
    renderWithApp(<FindingActivityPanel engagementId="prog-1" findingId="f1" readOnly />, { routes });
    await open();
    expect(await screen.findByText(/Re-ran the exploit/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save update" })).not.toBeInTheDocument();
  });

  it("posts a remediation note with no outcome, then reloads the timeline", async () => {
    const { authFetch } = renderWithApp(<FindingActivityPanel engagementId="prog-1" findingId="f1" readOnly={false} />, {
      routes: { ...routes, [`POST ${ACTIVITY}`]: { body: {} } },
    });
    await open();
    await screen.findByText(/Re-ran the exploit/);
    await userEvent.type(screen.getByLabelText("Update notes"), "Patched in release 4.2");
    await userEvent.click(screen.getByRole("button", { name: "Save update" }));
    await waitFor(() => expect(sent(authFetch as Authfetch, "POST", ACTIVITY).count).toBe(1));
    expect(sent(authFetch as Authfetch, "POST", ACTIVITY).body).toEqual({
      kind: "remediation", notes: "Patched in release 4.2", outcome: null, evidence_ids: [],
    });
    await waitFor(() => expect(sent(authFetch as Authfetch, "GET", LOAD).count).toBe(2));
  });

  it("asks for a verification outcome only for retests, and posts the one chosen", async () => {
    const { authFetch } = renderWithApp(<FindingActivityPanel engagementId="prog-1" findingId="f1" readOnly={false} />, {
      routes: { ...routes, [`POST ${ACTIVITY}`]: { body: {} } },
    });
    await open();
    await screen.findByText(/Re-ran the exploit/);
    expect(screen.queryByLabelText("Verification outcome")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Update type"), "retest");
    await userEvent.selectOptions(screen.getByLabelText("Verification outcome"), "verified_fixed");
    await userEvent.type(screen.getByLabelText("Update notes"), "Exploit now returns 403");
    await userEvent.click(screen.getByRole("button", { name: "Save update" }));
    await waitFor(() => expect(sent(authFetch as Authfetch, "POST", ACTIVITY).count).toBe(1));
    expect(sent(authFetch as Authfetch, "POST", ACTIVITY).body).toMatchObject({ kind: "retest", outcome: "verified_fixed" });
  });

  it("stores new evidence first and attaches it to the update", async () => {
    const EVIDENCE_POST = "/engagements/prog-1/evidence";
    const { authFetch } = renderWithApp(<FindingActivityPanel engagementId="prog-1" findingId="f1" readOnly={false} />, {
      routes: { ...routes, [`POST ${EVIDENCE_POST}`]: { body: { id: "e9", title: "x", body: "y" } }, [`POST ${ACTIVITY}`]: { body: {} } },
    });
    await open();
    await screen.findByText(/Re-ran the exploit/);
    await userEvent.type(screen.getByLabelText("Update notes"), "See evidence");
    await userEvent.type(screen.getByLabelText("New evidence (optional)"), "redacted response");
    await userEvent.click(screen.getByRole("button", { name: "Save update" }));
    await waitFor(() => expect(sent(authFetch as Authfetch, "POST", ACTIVITY).count).toBe(1));
    expect(sent(authFetch as Authfetch, "POST", EVIDENCE_POST).body).toMatchObject({ finding_id: "f1", sensitivity: "internal", body: "redacted response" });
    expect(sent(authFetch as Authfetch, "POST", ACTIVITY).body.evidence_ids).toEqual(["e9"]);
  });

  it("shows the server's message when saving fails", async () => {
    renderWithApp(<FindingActivityPanel engagementId="prog-1" findingId="f1" readOnly={false} />, {
      routes: { ...routes, [`POST ${ACTIVITY}`]: { ok: false, status: 400, body: { detail: "A retest requires an outcome" } } },
    });
    await open();
    await screen.findByText(/Re-ran the exploit/);
    await userEvent.type(screen.getByLabelText("Update notes"), "note");
    await userEvent.click(screen.getByRole("button", { name: "Save update" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A retest requires an outcome");
  });
});

// ── AuthorizationCaseBuilder ────────────────────────────────────────────────

describe("AuthorizationCaseBuilder", () => {
  const PREVIEW = "/engagements/prog-1/test-cases/preview";
  const SAVE = "/engagements/prog-1/test-cases/reviewed";
  const DRAFTS = [{ name: "GET /users/{id}", spec: { id: "case-1", request: { method: "GET", url: "https://api.example.test/users/1" } } }];
  const routes = {
    [`POST ${PREVIEW}`]: { body: { drafts: DRAFTS, total: 1 } },
    [`POST ${SAVE}`]: { body: { test_cases: [{ id: "tc1" }] } },
  };
  const draftBox = () => screen.getByLabelText("Draft cases JSON") as HTMLTextAreaElement;
  async function generate(endpointIds = ["ep1", "ep2"], overrides = {}) {
    const utils = renderWithApp(<AuthorizationCaseBuilder engagementId="prog-1" endpointIds={endpointIds} />, { routes, overrides });
    await userEvent.click(screen.getByRole("button", { name: "Generate draft cases" }));
    await screen.findByLabelText("Draft cases JSON");
    return utils;
  }

  it("cannot generate until at least one operation is selected", () => {
    renderWithApp(<AuthorizationCaseBuilder engagementId="prog-1" endpointIds={[]} />, { routes });
    expect(screen.getByRole("button", { name: "Generate draft cases" })).toBeDisabled();
  });

  it("previews drafts for the selected operations and says nothing was stored", async () => {
    const { authFetch } = renderWithApp(<AuthorizationCaseBuilder engagementId="prog-1" endpointIds={["ep1", "ep2"]} />, { routes });
    await userEvent.type(screen.getByLabelText("Base URL override (optional)"), "https://api.example.test");
    await userEvent.click(screen.getByRole("button", { name: "Generate draft cases" }));
    expect(await screen.findByRole("status")).toHaveTextContent("No cases have been stored or queued");
    expect(draftBox().value).toContain("GET /users/{id}");
    expect(sent(authFetch as Authfetch, "POST", PREVIEW).body).toEqual({
      endpoint_ids: ["ep1", "ep2"], base_url: "https://api.example.test", limit: 50, offset: 0,
    });
  });

  it("will not save until the operator confirms review, then saves exactly what is in the box", async () => {
    const { authFetch } = await generate();
    const save = screen.getByRole("button", { name: "Save reviewed cases" });
    expect(save).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/I reviewed the request targets/));
    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(await screen.findByRole("status")).toHaveTextContent("1 reviewed cases saved");
    expect(sent(authFetch as Authfetch, "POST", SAVE).body).toEqual({ reviewed: true, cases: DRAFTS });
  });

  it("withdraws the review confirmation whenever the drafts are edited", async () => {
    await generate();
    await userEvent.click(screen.getByLabelText(/I reviewed the request targets/));
    fireEvent.change(draftBox(), { target: { value: "[]" } });
    expect(screen.getByLabelText(/I reviewed the request targets/)).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save reviewed cases" })).toBeDisabled();
  });

  it("reports unreadable drafts and sends nothing", async () => {
    const { authFetch } = await generate();
    fireEvent.change(draftBox(), { target: { value: "not json" } });
    await userEvent.click(screen.getByLabelText(/I reviewed the request targets/));
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed cases" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(sent(authFetch as Authfetch, "POST", SAVE).count).toBe(0);
  });

  it("rejects drafts that are not a JSON array", async () => {
    const { authFetch } = await generate();
    fireEvent.change(draftBox(), { target: { value: '{"name":"x"}' } });
    await userEvent.click(screen.getByLabelText(/I reviewed the request targets/));
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed cases" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must be a JSON array");
    expect(sent(authFetch as Authfetch, "POST", SAVE).count).toBe(0);
  });

  it("lets viewers preview but never save", async () => {
    await generate(["ep1"], { selectedEngagement: VIEWER });
    expect(draftBox().value).toContain("GET /users/{id}");
    expect(screen.queryByRole("button", { name: "Save reviewed cases" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/I reviewed the request targets/)).not.toBeInTheDocument();
  });

  it("shows the server's message when the preview is refused", async () => {
    renderWithApp(<AuthorizationCaseBuilder engagementId="prog-1" endpointIds={["ep1"]} />, {
      routes: { [`POST ${PREVIEW}`]: { ok: false, status: 400, body: { detail: "Provide an absolute HTTP(S) base_url" } } },
    });
    await userEvent.click(screen.getByRole("button", { name: "Generate draft cases" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("absolute HTTP(S) base_url");
  });
});

// ── EngagementDeliverables ──────────────────────────────────────────────────

describe("EngagementDeliverables", () => {
  const BASE = "/engagements/prog-1/deliverables";
  const EDITORIAL = { title: "Q4 report", executive_summary: "Summary", methodology: "", limitations: "", remediation_priorities: "", finding_ids: null, evidence_ids: [] };
  const REVISION = {
    id: "r2", deliverable_id: "d1", revision: 2, status: "draft", content_hash: "deadbeef",
    markdown: "# Q4 report\n\nbody text", snapshot: { editorial: EDITORIAL }, created_at: "2026-10-09T01:00:00Z",
  };
  const routes = {
    [`GET ${BASE}?limit=50&offset=0`]: { body: { deliverables: [{ id: "d1", title: "Q4 report", latest_revision: 2 }], total: 1 } },
    [`GET ${BASE}/d1/revisions/2`]: { body: REVISION },
    [`GET ${BASE}/d1/revisions?limit=50&offset=0`]: { body: { revisions: [REVISION], total: 1 } },
  };
  async function openLatest(engagement = PROGRAM, extra = {}) {
    const utils = renderWithApp(<EngagementDeliverables engagement={engagement} />, { routes: { ...routes, ...extra } });
    await userEvent.click(await screen.findByRole("button", { name: "Q4 report · v2" }));
    await screen.findByText(/Revision 2/);
    return utils;
  }

  it("lists reports and opens one with its content hash and rendered markdown", async () => {
    await openLatest();
    expect(screen.getByText("SHA-256 deadbeef")).toBeInTheDocument();
    expect(screen.getByText(/^# Q4 report/)).toBeInTheDocument();
  });

  it("creates revision 1 including all findings, with no base revision", async () => {
    const { authFetch } = renderWithApp(<EngagementDeliverables engagement={PROGRAM} />, {
      routes: { ...routes, [`POST ${BASE}`]: { body: { ...REVISION, revision: 1 } } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "New engagement report" }));
    await userEvent.type(screen.getByLabelText("Executive summary"), "All good");
    await userEvent.click(screen.getByRole("button", { name: "Create revision 1" }));
    await waitFor(() => expect(sent(authFetch as Authfetch, "POST", BASE).count).toBe(1));
    const body = sent(authFetch as Authfetch, "POST", BASE).body;
    expect(body).toMatchObject({ title: "Engagement assessment", executive_summary: "All good", finding_ids: null, evidence_ids: [] });
    expect(body).not.toHaveProperty("base_revision");
  });

  it("saves a new revision against the revision it was based on", async () => {
    const { authFetch } = await openLatest(PROGRAM, { [`POST ${BASE}/d1/revisions`]: { body: { ...REVISION, revision: 3 } } });
    await userEvent.click(screen.getByRole("button", { name: "Draft next revision" }));
    await userEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    await waitFor(() => expect(sent(authFetch as Authfetch, "POST", `${BASE}/d1/revisions`).count).toBe(1));
    expect(sent(authFetch as Authfetch, "POST", `${BASE}/d1/revisions`).body.base_revision).toBe(2);
  });

  it("explains a stale-revision conflict instead of overwriting", async () => {
    await openLatest(PROGRAM, {
      [`POST ${BASE}/d1/revisions`]: { ok: false, status: 409, body: { detail: "A newer revision exists; reload it before saving" } },
    });
    await userEvent.click(screen.getByRole("button", { name: "Draft next revision" }));
    await userEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A newer revision exists");
  });

  it("changes a revision's workflow status", async () => {
    const { authFetch } = await openLatest(PROGRAM, { [`PATCH ${BASE}/d1/revisions/2`]: { body: { ...REVISION, status: "final" } } });
    await userEvent.selectOptions(screen.getByLabelText("Report revision status"), "final");
    await waitFor(() => expect(sent(authFetch as Authfetch, "PATCH", `${BASE}/d1/revisions/2`).count).toBe(1));
    expect(sent(authFetch as Authfetch, "PATCH", `${BASE}/d1/revisions/2`).body).toEqual({ status: "final" });
  });

  it("is read-only for viewers", async () => {
    await openLatest(VIEWER);
    expect(screen.queryByRole("button", { name: "New engagement report" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Draft next revision" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Report revision status")).toBeDisabled();
    // Reading and exporting are still available.
    expect(screen.getByRole("button", { name: "Download Markdown" })).toBeInTheDocument();
  });
});
