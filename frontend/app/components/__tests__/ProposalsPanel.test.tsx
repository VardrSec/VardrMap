import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ProposalsPanel -> ui.tsx -> react-markdown/remark-gfm (ESM); mock so the
// CommonJS jest runtime can import the component.
jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import ProposalsPanel from "../ProposalsPanel";
import { Engagement } from "../../types";

function engagement(): Engagement {
  return { id: "e1", name: "Acme", scope: { in: [], out: [] } } as unknown as Engagement;
}

const PENDING = {
  proposals: [
    {
      id: "p1",
      kind: "scope_in",
      payload: { value: "branch.remitly.com", kind: "domain", max_severity: "critical" },
      reason: "Listed in the HackerOne scope table",
      source: "https://hackerone.com/remitly",
      proposed_by: "mcp-agent",
      status: "pending",
    },
  ],
};

test("renders nothing when there are no pending proposals", async () => {
  const { container } = renderWithApp(<ProposalsPanel engagement={engagement()} />, {
    routes: { "GET /engagements/e1/proposals?status=pending": { body: { proposals: [] } } },
  });
  await waitFor(() => {
    expect(container.querySelector("button")).toBeNull();
  });
});

test("shows a pending proposal with its reason and source, and approves it", async () => {
  const { authFetch } = renderWithApp(<ProposalsPanel engagement={engagement()} />, {
    routes: {
      "GET /engagements/e1/proposals?status=pending": { body: PENDING },
      "POST /engagements/e1/proposals/p1/approve": { body: { id: "p1", status: "approved" } },
    },
  });

  expect(await screen.findByText(/Add in-scope: branch.remitly.com/)).toBeInTheDocument();
  expect(screen.getByText(/Listed in the HackerOne scope table/)).toBeInTheDocument();
  expect(screen.getByText(/hackerone.com\/remitly/)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => {
    const call = authFetch.mock.calls.find((c) => String(c[0]).endsWith("/proposals/p1/approve"));
    expect(call).toBeTruthy();
    expect((call?.[1] as RequestInit).method).toBe("POST");
  });
});

test("rejecting posts to the reject endpoint", async () => {
  const { authFetch } = renderWithApp(<ProposalsPanel engagement={engagement()} />, {
    routes: {
      "GET /engagements/e1/proposals?status=pending": { body: PENDING },
      "POST /engagements/e1/proposals/p1/reject": { body: { id: "p1", status: "rejected" } },
    },
  });

  await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
  await waitFor(() => {
    expect(authFetch.mock.calls.find((c) => String(c[0]).endsWith("/proposals/p1/reject"))).toBeTruthy();
  });
});
