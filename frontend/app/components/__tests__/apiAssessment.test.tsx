import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));
import { renderWithApp } from "../../../test-utils/renderWithApp";
import type { Engagement, ScanJobUI } from "../../types";
import ApiPlaybookGuide from "../ApiPlaybookGuide";
import AssessmentBadge from "../jobs/AssessmentBadge";
import GateAssessmentPanel from "../jobs/GateAssessmentPanel";

const base = "/engagements/eng";
const job: ScanJobUI = { id: "job", tool: "vardrgate_api_test", source: "scope", config: {}, status: "done", targets: 1, progress: 100, yield: 0, yieldKind: "findings", queuedAt: "2026-10-11T01:00:00Z", startedAt: null, endedAt: null, durationMs: null, log: [], assessment: {
  status: "inconclusive", evaluated: 0, inconclusive: 2, missing: 0, skipped: 0, unexpected: 0, baseline_valid: false, case_snapshot_verified: true, candidate_findings: 0, reasons: ["legitimate_baseline_missing"], case_id: "case", case_ref: "ownership", case_hash: "abc123", identities: [{ identity_id: "OwnerA", expected_decision: "allow", observed_outcome: "server_error", state: "inconclusive", reason: "ambiguous_response" }],
} };
const evidence = { id: "e1", title: "Owner execution", job_id: "job", case_id: "case", case_ref: "ownership", identity_id: "OwnerA", expected_decision: "allow", observed_outcome: "server_error", body: "redacted record", content_hash: "abc", finding_id: "" };
const evidencePath = `${base}/evidence?job_id=job&limit=50&offset=0`;
const guide = { id: "API-01", title: "Object ownership", version: "1.0", use_when: "Use known owned objects", expected_artifacts: "Reviewed case", prerequisites: ["Establish baseline"], steps: ["Review expected access"], common_traps: "Stale credentials", manual_remainder: "Verify business impact" };

it("separates scanner conclusions, raw HTTP, credential checks and readback", async () => {
  const enriched: ScanJobUI = { ...job, assessment: { ...job.assessment!, identities: [{ identity_id: "peer", expected_decision: "deny", observed_outcome: "allow", state: "evaluated", reason: "reported_write_verification", reported_decision: "denied", source: "write_verification", credential_status: "preflight_passed", write_verification: "verified_no_effect", verification: { strategy: "changed", environment: "synchronous_isolated", reader_identity_id: "reader", reader_credential_status: "not_checked", before_statuses: [200, 200], after_status: 200, reset_status: 204 } }] } };
  renderWithApp(<GateAssessmentPanel engagementId="eng" job={enriched} />, { routes: { [evidencePath]: { body: { evidence: [], total: 0 } } } });
  expect(screen.getByText("peer: expected deny · raw HTTP outcome allow")).toBeVisible();
  expect(screen.getByText(/Scanner assessment: denied/)).toBeVisible();
  expect(screen.getByText(/Credential check: preflight passed · write readback: verified no effect/)).toBeVisible();
  expect(screen.getByText(/Reader reader: not checked · before HTTP 200, 200 · after HTTP 200/)).toBeVisible();
  expect(screen.getByText(/scanner conclusions still need operator confirmation/)).toBeVisible();
  await screen.findByText("No execution evidence recorded for this job.");
});

it("reads versioned guidance on demand and performs no writes", async () => {
  const { authFetch } = renderWithApp(<ApiPlaybookGuide engagementId="eng" />, { routes: {
    [`${base}/playbooks`]: { body: { playbooks: [guide], total: 1 } }, [`${base}/playbooks/API-01`]: { body: guide },
  } });
  expect(authFetch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Show API playbooks" }));
  expect(await screen.findByText("API-01 · version 1.0")).toBeVisible();
  expect(screen.getByText("Verify business impact")).toBeVisible();
  expect(screen.getByText(/records no testing progress/)).toBeVisible();
  expect(authFetch.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
});

it("keeps an inconclusive assessment visible on a completed job", async () => {
  renderWithApp(<><AssessmentBadge job={job} /><GateAssessmentPanel engagementId="eng" job={job} /></>, { routes: { [evidencePath]: { body: { evidence: [evidence], total: 1 } } } });
  expect(screen.getByText("Assessment: inconclusive")).toBeVisible();
  expect(screen.getByText(/Job completion alone/)).toBeVisible();
  expect(screen.getByText(/Legitimate baseline: not established/)).toBeVisible();
  expect(await screen.findByText(/Case: ownership · Identity: OwnerA/)).toBeVisible();
  expect(screen.getByText(/Evidence e1 · Job job · Case case/)).toBeVisible();
});

it("links the original evidence to the selected finding and retains provenance", async () => {
  const linkPath = `${base}/evidence/e1/link`;
  const { authFetch } = renderWithApp(<GateAssessmentPanel engagementId="eng" job={job} />, { routes: {
    [evidencePath]: { body: { evidence: [evidence], total: 1 } }, [`${base}/findings?limit=50&offset=0`]: { body: { findings: [{ id: "f1", title: "Ownership issue" }], total: 1 } }, [`POST ${linkPath}`]: { body: { ...evidence, finding_id: "f1" } },
  } });
  await screen.findByText("Owner execution");
  await userEvent.click(screen.getByRole("button", { name: "Link evidence to a finding" }));
  await screen.findByRole("option", { name: "Ownership issue" });
  await userEvent.selectOptions(screen.getByLabelText("Finding for selected evidence"), "f1");
  await userEvent.click(screen.getByRole("button", { name: "Link this evidence" }));
  expect(await screen.findByText("Linked finding: f1")).toBeVisible();
  const call = authFetch.mock.calls.find(([path]) => path === linkPath);
  expect(call?.[1]?.method).toBe("POST");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ finding_id: "f1" });
  expect(screen.getByText(/Evidence e1 · Job job · Case case/)).toBeVisible();
});

it("viewers can read evidence but cannot link it", async () => {
  renderWithApp(<GateAssessmentPanel engagementId="eng" job={job} />, { overrides: { selectedEngagement: { my_role: "viewer" } as Engagement }, routes: { [evidencePath]: { body: { evidence: [evidence], total: 1 } } } });
  await screen.findByText("Owner execution");
  expect(screen.queryByRole("button", { name: "Link evidence to a finding" })).not.toBeInTheDocument();
});

it("an unavailable evidence read is not presented as an empty result", async () => {
  renderWithApp(<GateAssessmentPanel engagementId="eng" job={job} />, { routes: { [evidencePath]: { ok: false, status: 503, body: { detail: "Evidence unavailable" } } } });
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Evidence unavailable"));
  expect(screen.queryByText("No execution evidence recorded for this job.")).not.toBeInTheDocument();
});

it("historical completion without an assessment stays unrecorded", () => {
  renderWithApp(<AssessmentBadge job={{ ...job, assessment: null }} />);
  expect(screen.getByText("Assessment: not recorded")).toBeVisible();
});

it("shows a failed session preflight separately from authorization outcomes", async () => {
  const failed = { ...job, status: "failed" as const, assessment: { ...job.assessment!, preflight: { status: "failed" as const, unexpected: 0, identities: [{ identity_id: "OwnerA", status: "failed", reason: "credential_rejected", status_code: 401 }] } } };
  renderWithApp(<GateAssessmentPanel engagementId="eng" job={failed} />, { routes: { [evidencePath]: { body: { evidence: [], total: 0 } } } });
  expect(screen.getByText(/Identity preflight: failed/)).toBeVisible();
  expect(screen.getByText("Session OwnerA: failed (credential rejected) · HTTP 401")).toBeVisible();
  expect(screen.getByText(/Legitimate baseline: not established/)).toBeVisible();
  await screen.findByText("No execution evidence recorded for this job.");
});
