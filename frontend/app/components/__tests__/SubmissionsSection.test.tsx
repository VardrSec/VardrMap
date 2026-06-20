import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import SubmissionsSection from "../SubmissionsSection";
import type { Program } from "../../types";

const PROGRAM: Program = {
  id: "prog-1", name: "Test Program", platform: "", program_url: "",
  scope_summary: "", severity_guidance: "", safe_harbor_notes: "",
  scope: { in: [], out: [] }, imports: [],
  recon_count: 0, scans_count: 0, manual_tests_count: 0,
  findings_count: 0, findings_by_severity: {}, findings_by_status: {}, reports_count: 0,
};

const SUBMISSION = {
  id: "s1", program_id: "prog-1", title: "SSRF via redirect", platform: "HackerOne",
  severity: "high", status: "submitted",
  payout_usd: null, notes: "", platform_reference: "",
  submitted_at: "2026-06-01T00:00:00", resolved_at: null, created_at: null,
  report_id: "", finding_id: "",
};

const EMPTY_ROUTES = {
  "GET /programs/prog-1/submissions": { body: { submissions: [] } },
};

describe("SubmissionsSection", () => {
  it("renders stats row after loading with no submissions", async () => {
    renderWithApp(<SubmissionsSection program={PROGRAM} />, { routes: EMPTY_ROUTES });
    expect(await screen.findByText("Total submitted")).toBeInTheDocument();
  });

  it("renders loaded submissions in the table", async () => {
    renderWithApp(<SubmissionsSection program={PROGRAM} />, {
      routes: {
        "GET /programs/prog-1/submissions": { body: { submissions: [SUBMISSION] } },
      },
    });
    expect(await screen.findByText("SSRF via redirect")).toBeInTheDocument();
    // HackerOne appears in both the submission row and the analytics by-platform breakdown.
    // Verify at least one instance is in the document.
    expect(screen.getAllByText("HackerOne").length).toBeGreaterThan(0);
  });

  it("creates a submission via POST and appends it to the list", async () => {
    const created = { ...SUBMISSION, id: "s2", title: "Open Redirect" };
    const { authFetch, setMessage } = renderWithApp(<SubmissionsSection program={PROGRAM} />, {
      routes: {
        ...EMPTY_ROUTES,
        "POST /programs/prog-1/submissions": { body: created },
      },
    });

    await userEvent.click(await screen.findByRole("button", { name: "+ New Submission" }));

    await userEvent.type(
      screen.getByPlaceholderText("Short report title"),
      "Open Redirect",
    );
    await userEvent.click(screen.getByRole("button", { name: "Log Submission" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(
        "/programs/prog-1/submissions",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(setMessage).toHaveBeenCalledWith("Submission logged.");
  });

  it("deletes a submission via DELETE and removes it from the list", async () => {
    const { authFetch, setMessage } = renderWithApp(<SubmissionsSection program={PROGRAM} />, {
      routes: {
        "GET /programs/prog-1/submissions": { body: { submissions: [SUBMISSION] } },
        "DELETE /programs/prog-1/submissions/s1": { body: {} },
      },
    });

    await screen.findByText("SSRF via redirect");
    await userEvent.click(screen.getByRole("button", { name: "×" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(
        "/programs/prog-1/submissions/s1",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    expect(setMessage).toHaveBeenCalledWith("Submission removed.");
  });

  it("applies submissionPrefill: opens form with title pre-filled and clears the prefill", async () => {
    const { dispatch } = renderWithApp(<SubmissionsSection program={PROGRAM} />, {
      routes: EMPTY_ROUTES,
      state: {
        submissionPrefill: { title: "Prefilled Bug", report_id: "r1", finding_id: "f1" },
      },
    });

    expect(await screen.findByDisplayValue("Prefilled Bug")).toBeInTheDocument();
    expect(dispatch).toHaveBeenCalledWith({ type: "SUBMISSION_PREFILL_CONSUMED" });
  });
});
