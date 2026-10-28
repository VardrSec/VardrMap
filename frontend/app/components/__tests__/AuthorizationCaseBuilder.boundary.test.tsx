import "@testing-library/jest-dom";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import AuthorizationCaseBuilder from "../AuthorizationCaseBuilder";

const draft = {
  name: "GET /orders/{id}", description: "Draft", spec: {
    id: "case-1", request: { method: "GET", url: "https://api.example.com/orders/{id}" },
    identities: [{ id: "owner", credential: { type: "bearer", value_env: "OWNER_TOKEN" } }],
    expected_access: [{ identity_id: "owner", decision: "skip" }],
  },
};
const previewRoute = "POST /engagements/eng-1/test-cases/preview";

describe("AuthorizationCaseBuilder boundary drafts", () => {
  it("asks the existing preview endpoint for a boundary draft and lists what is missing", async () => {
    const { authFetch } = renderWithApp(<AuthorizationCaseBuilder engagementId="eng-1" endpointIds={["ep-1"]} boundary="cross_tenant" />, {
      routes: { [previewRoute]: { body: {
        drafts: [draft], total: 1, offset: 0, limit: 50, next_offset: null,
        boundary_context: {
          boundary: "cross_tenant", ready_to_run: false,
          missing_context: ["resource.owner_identity: no reviewed case for this operation says who owns the object under test."],
          conflicts: [{ identity_id: "visitor", attribute: "tenant_id", values: ["tenant-b", "tenant-c"] }],
        },
      } } },
    });
    await userEvent.click(screen.getByRole("button", { name: "Generate draft cases" }));
    expect(await screen.findByText(/Not ready to run/)).toBeInTheDocument();
    expect(screen.getByText(/resource.owner_identity: no reviewed case/)).toBeInTheDocument();
    expect(screen.getByText(/visitor tenant_id \(tenant-b vs tenant-c\)/)).toBeInTheDocument();
    expect(screen.getByText(/Every expected access is/)).toBeInTheDocument();
    const call = authFetch.mock.calls.find((c) => String(c[0]).endsWith("/preview"))!;
    const sent = JSON.parse(String(call[1]?.body));
    expect(sent).toMatchObject({ endpoint_ids: ["ep-1"], boundary: "cross_tenant" });
    expect(sent).not.toHaveProperty("identity_ids");
  });

  it("stores nothing: saving still needs the explicit review confirmation", async () => {
    const { authFetch } = renderWithApp(<AuthorizationCaseBuilder engagementId="eng-1" endpointIds={["ep-1"]} boundary="anonymous" />, {
      routes: { [previewRoute]: { body: { drafts: [draft], total: 1, offset: 0, limit: 50, next_offset: null, boundary_context: { boundary: "anonymous", ready_to_run: false, missing_context: [], conflicts: [] } } } },
    });
    await userEvent.click(screen.getByRole("button", { name: "Generate draft cases" }));
    const save = await screen.findByRole("button", { name: "Save reviewed cases" });
    expect(save).toBeDisabled();
    expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith("/reviewed"))).toBe(false);
  });

  it("has no boundary notice for an ordinary draft", async () => {
    renderWithApp(<AuthorizationCaseBuilder engagementId="eng-1" endpointIds={["ep-1"]} />, {
      routes: { [previewRoute]: { body: { drafts: [draft], total: 1, offset: 0, limit: 50, next_offset: null } } },
    });
    await userEvent.click(screen.getByRole("button", { name: "Generate draft cases" }));
    await screen.findByLabelText("Draft cases JSON");
    expect(screen.queryByText(/Not ready to run/)).not.toBeInTheDocument();
  });
});
