import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import AuthorizationRelationshipsPanel from "../AuthorizationRelationshipsPanel";

const hypothesis = (id: string, status = "untested", boundary = "cross_tenant") => ({
  id, endpoint_id: `e-${id}`, operation: `GET /orders/{id}#${id}`, boundary, status,
  question: "Has a caller from a different tenant been shown to be denied (or allowed) on GET /orders/{id}?",
  basis: ["Identities are declared in tenants: tenant-a, tenant-b.", "The route addresses an object by identifier (object-level access)."],
});
const base = {
  identities: [{ identity_id: "owner", role: "user", tenant_id: "tenant-a", anonymous: false }],
  tenants: ["tenant-a", "tenant-b"],
  askable_boundaries: { cross_tenant: true, same_tenant_peer: false, higher_privilege: false, anonymous: true },
  identities_without_tenant: [], summary: {},
};
const route = (body: unknown) => ({ "GET /engagements/eng-1/api/relationships?limit=500": { body } });

describe("AuthorizationRelationshipsPanel", () => {
  it("presents hypotheses with their basis and says they are not findings", async () => {
    renderWithApp(<AuthorizationRelationshipsPanel engagementId="eng-1" />, {
      routes: route({ ...base, hypotheses: [hypothesis("a")] }),
    });
    expect(await screen.findByText(/Has a caller from a different tenant/)).toBeInTheDocument();
    expect(screen.getByText(/Identities are declared in tenants: tenant-a, tenant-b/)).toBeInTheDocument();
    expect(screen.getByText(/hypotheses, not findings/)).toBeInTheDocument();
    expect(screen.getByText("No evaluated test")).toBeInTheDocument();
    expect(screen.getAllByText("Different tenant").length).toBeGreaterThanOrEqual(2); // the testable-boundary chip and this question
  });

  it("lists which boundaries the declared identities make testable", async () => {
    renderWithApp(<AuthorizationRelationshipsPanel engagementId="eng-1" />, {
      routes: route({ ...base, hypotheses: [hypothesis("a")] }),
    });
    await screen.findByText(/Boundaries your identities make testable/);
    expect(screen.getAllByText("Different tenant").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No credentials").length).toBeGreaterThan(0);
    expect(screen.queryByText("Same-tenant peer")).not.toBeInTheDocument();
  });

  it("warns when identities have no declared tenant instead of assuming one", async () => {
    renderWithApp(<AuthorizationRelationshipsPanel engagementId="eng-1" />, {
      routes: route({ ...base, identities_without_tenant: ["contractor"], hypotheses: [] }),
    });
    expect(await screen.findByText(/No tenant is declared for contractor/)).toBeInTheDocument();
    expect(screen.getByText(/Every testable boundary has a current, evaluated result/)).toBeInTheDocument();
  });

  it("collapses a long list until asked", async () => {
    const many = Array.from({ length: 15 }, (_, i) => hypothesis(String(i)));
    renderWithApp(<AuthorizationRelationshipsPanel engagementId="eng-1" />, { routes: route({ ...base, hypotheses: many }) });
    await screen.findByText("GET /orders/{id}#0");
    expect(screen.queryByText("GET /orders/{id}#14")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show all 15" }));
    expect(await screen.findByText("GET /orders/{id}#14")).toBeInTheDocument();
  });

  it("renders nothing when there is nothing declared to reason about", async () => {
    const { container } = renderWithApp(<AuthorizationRelationshipsPanel engagementId="eng-1" />, {
      routes: route({ ...base, identities: [], hypotheses: [] }),
    });
    await waitFor(() => expect(container.textContent).not.toContain("Boundary questions"));
  });
});


describe("AuthorizationRelationshipsPanel drafting and conflicts", () => {
  it("offers Draft authorization test on each question and passes the operation and boundary", async () => {
    const onDraft = jest.fn();
    renderWithApp(<AuthorizationRelationshipsPanel engagementId="eng-1" onDraft={onDraft} />, {
      routes: route({ ...base, hypotheses: [hypothesis("a"), hypothesis("b", "untested", "anonymous")] }),
    });
    const buttons = await screen.findAllByRole("button", { name: /Draft authorization test:/ });
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons[1]);
    expect(onDraft).toHaveBeenCalledWith("e-b", "anonymous");
  });

  it("does not offer the action when no handler is wired", async () => {
    renderWithApp(<AuthorizationRelationshipsPanel engagementId="eng-1" />, { routes: route({ ...base, hypotheses: [hypothesis("a")] }) });
    await screen.findByText(/Has a caller from a different tenant/);
    expect(screen.queryByRole("button", { name: /Draft authorization test/ })).not.toBeInTheDocument();
  });

  it("names contradictory identity declarations and says they are not used", async () => {
    renderWithApp(<AuthorizationRelationshipsPanel engagementId="eng-1" />, {
      routes: route({ ...base, identity_conflicts: [{ identity_id: "peer", attribute: "tenant_id", values: ["tenant-a", "tenant-b"] }], hypotheses: [] }),
    });
    expect(await screen.findByText(/Contradictory identity declarations \(not used until you resolve them\)/)).toBeInTheDocument();
    expect(screen.getByText(/tenant id: tenant-a vs tenant-b/)).toBeInTheDocument();
  });
});
