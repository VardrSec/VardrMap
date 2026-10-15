import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ScopeSection -> ui.tsx -> react-markdown/remark-gfm (ESM); mock so the
// CommonJS jest runtime can import the component.
jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import ScopeSection from "../ScopeSection";
import { Engagement } from "../../types";

function engagement(): Engagement {
  return {
    id: "e1", name: "Acme", platform: "", program_url: "",
    scope_summary: "", severity_guidance: "", safe_harbor_notes: "",
    client_id: "", engagement_type: "bug_bounty", engagement_status: "active",
    starts_at: "", ends_at: "",
    scope: { in: [{ id: "s1", value: "api.acme.com", kind: "api", notes: "", max_severity: "high" }], out: [] },
    imports: [], recon_count: 0, scans_count: 0, manual_tests_count: 0,
    findings_count: 0, findings_by_severity: {}, findings_by_status: {}, reports_count: 0,
  } as unknown as Engagement;
}

const PREVIEW = {
  committed: false, created: 0,
  summary: { in: 2, out: 1, duplicates: 1, skipped: 1, total_rows: 5 },
  skipped: [{ line: 4, identifier: "<bad>", reason: "invalid characters" }],
};

test("shows the per-asset severity cap in the scope list", () => {
  renderWithApp(<ScopeSection engagement={engagement()} />);
  expect(screen.getByText(/api — max high/)).toBeInTheDocument();
});

test("previews an import without committing, then imports", async () => {
  const { authFetch, container } = renderWithApp(<ScopeSection engagement={engagement()} />, {
    routes: {
      "POST /engagements/e1/scope/import": { body: PREVIEW },
    },
  });
  // The import CSV box is the first textarea on the page.
  const csvBox = container.querySelector("textarea") as HTMLTextAreaElement;
  await userEvent.type(csvBox, "identifier\nx.acme.com\n");
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));

  // The preview summary and the skipped reason are shown; nothing was committed.
  expect(await screen.findByText(/2 in-scope · 1 out-of-scope · 1 already present · 1 skipped/)).toBeInTheDocument();
  expect(screen.getByText(/line 4 \(invalid characters\)/)).toBeInTheDocument();
  const firstCall = authFetch.mock.calls[0];
  expect(JSON.parse((firstCall[1] as RequestInit).body as string).commit).toBe(false);

  // Clicking import sends commit:true.
  await userEvent.click(screen.getByRole("button", { name: /Import 3 new items/ }));
  await waitFor(() => {
    const commitCall = authFetch.mock.calls.find(
      (c) => JSON.parse((c[1] as RequestInit).body as string).commit === true,
    );
    expect(commitCall).toBeTruthy();
  });
});
