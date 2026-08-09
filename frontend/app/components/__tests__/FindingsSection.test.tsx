import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import FindingsSection from "../FindingsSection";
import type { Engagement } from "../../types";

const PROGRAM: Engagement = {
  id: "prog-1", name: "Test Engagement", platform: "", program_url: "",
  scope_summary: "", severity_guidance: "", safe_harbor_notes: "",
  client_id: "", engagement_type: "bug_bounty", engagement_status: "active",
  starts_at: "", ends_at: "",
  scope: { in: [], out: [] }, imports: [],
  recon_count: 0, scans_count: 0, manual_tests_count: 0,
  findings_count: 0, findings_by_severity: {}, findings_by_status: {}, reports_count: 0,
  services_count: 0,
};

const FINDING = {
  id: "f1", title: "SQL Injection", severity: "high", asset: "api.example.com",
  status: "new", summary: "Classic SQLi", steps: "", impact: "", remediation: "",
  created_at: null,
};

const EMPTY_ROUTES = {
  "GET /engagements/prog-1/findings?limit=50&offset=0": { body: { findings: [], total: 0 } },
};

describe("FindingsSection", () => {
  it("shows empty state when there are no findings", async () => {
    renderWithApp(<FindingsSection engagement={PROGRAM} />, { routes: EMPTY_ROUTES });
    expect(await screen.findByText("No findings yet.")).toBeInTheDocument();
  });

  it("renders loaded findings on mount", async () => {
    renderWithApp(<FindingsSection engagement={PROGRAM} />, {
      routes: {
        "GET /engagements/prog-1/findings?limit=50&offset=0": {
          body: { findings: [FINDING], total: 1 },
        },
      },
    });
    expect(await screen.findByText("SQL Injection")).toBeInTheDocument();
  });

  it("adds a finding via POST and shows success message", async () => {
    const created = { ...FINDING, id: "f2", title: "XSS" };
    const { authFetch, setMessage } = renderWithApp(<FindingsSection engagement={PROGRAM} />, {
      routes: {
        ...EMPTY_ROUTES,
        "POST /engagements/prog-1/findings": { body: created },
      },
    });

    // Input component has no htmlFor — select by role index (Title is first textbox)
    await userEvent.type(screen.getAllByRole("textbox")[0], "XSS");
    await userEvent.click(screen.getByRole("button", { name: "Save Finding" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(
        "/engagements/prog-1/findings",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(setMessage).toHaveBeenCalledWith("Finding added.");
  });

  it("deletes a finding via DELETE", async () => {
    window.confirm = jest.fn(() => true);
    const { authFetch, setMessage } = renderWithApp(<FindingsSection engagement={PROGRAM} />, {
      routes: {
        "GET /engagements/prog-1/findings?limit=50&offset=0": {
          body: { findings: [FINDING], total: 1 },
        },
        "DELETE /engagements/prog-1/findings/f1": { body: {} },
      },
    });

    await screen.findByText("SQL Injection");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(
        "/engagements/prog-1/findings/f1",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    expect(setMessage).toHaveBeenCalledWith("Finding deleted.");
  });

  it("promotes a finding to report via promoteToReport", async () => {
    const { value } = renderWithApp(<FindingsSection engagement={PROGRAM} />, {
      routes: {
        "GET /engagements/prog-1/findings?limit=50&offset=0": {
          body: { findings: [FINDING], total: 1 },
        },
      },
    });

    await screen.findByText("SQL Injection");
    await userEvent.click(screen.getByRole("button", { name: "Draft Report →" }));

    expect(value.promoteToReport).toHaveBeenCalledWith(
      expect.objectContaining({ id: "f1" }),
    );
  });

  it("applies AI suggestion via POST /suggest and enters edit mode", async () => {
    const { authFetch, setMessage } = renderWithApp(<FindingsSection engagement={PROGRAM} />, {
      routes: {
        "GET /engagements/prog-1/findings?limit=50&offset=0": {
          body: { findings: [FINDING], total: 1 },
        },
        "POST /engagements/prog-1/findings/f1/suggest": {
          body: { impact: "Database exfiltration", remediation: "Use parameterized queries", cvss: "9.8" },
        },
      },
    });

    await screen.findByText("SQL Injection");
    await userEvent.click(screen.getByRole("button", { name: "AI Suggest" }));

    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith(
        "/engagements/prog-1/findings/f1/suggest",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(setMessage).toHaveBeenCalledWith("AI suggestion applied. CVSS: 9.8");
  });
});
