import "@testing-library/jest-dom";
import { fireEvent, screen, within } from "@testing-library/react";
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
const reviewedRoute = "POST /engagements/eng-1/test-cases/reviewed";

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

describe("AuthorizationCaseBuilder identity review", () => {
  async function openReview(cases: unknown[]) {
    const result = renderWithApp(<AuthorizationCaseBuilder engagementId="eng-1" endpointIds={["ep-1"]} />, {
      routes: {
        [previewRoute]: { body: { drafts: cases, total: cases.length } },
        [reviewedRoute]: { body: { test_cases: [{}] } },
      },
    });
    await userEvent.click(screen.getByRole("button", { name: "Generate draft cases" }));
    await userEvent.click(await screen.findByText("Review draft identities"));
    return result;
  }

  it("shows declared access and only the credential source for each identity", async () => {
    const spec = {
      ...draft.spec, resource: { owner_identity: "owner", tenant_id: "resource-tenant" },
      identities: [
        { ...draft.spec.identities[0], role: "editor", tenant_id: "tenant-a" },
        { id: "peer", role: "reader", tenant_id: "tenant-b", credential: { type: "bearer", value_keychain: "private-keychain-entry" } },
        { id: "guest", credential: { type: "static_header", header: "", value: "" } },
        { id: "unreviewed", credential: { type: "bearer", value: "invalid-literal-marker" } },
        { id: "missing-header", credential: { type: "static_header", value_env: "MISSING_HEADER_REF" } },
        { id: "missing-reference", credential: { type: "static_header", header: "X-Identity" } },
      ],
      expected_access: [
        { identity_id: "owner", decision: "allow" }, { identity_id: "peer", decision: "allow" },
        { identity_id: "peer", decision: "deny" }, { identity_id: "guest", decision: "skip" },
      ],
    };
    const { authFetch } = await openReview([{ ...draft, spec }]);
    expect(screen.getByText(/Resource owner: owner.*Resource tenant: resource-tenant/i)).toBeVisible();
    const table = screen.getByRole("table", { name: "Draft identities" });
    const expectedRows = [
      ["owner", "editor", "tenant-a", "Environment reference", "allow"],
      ["peer", "reader", "tenant-b", "Keychain reference", "Conflicting decisions"],
      ["guest", "Not declared", "Not declared", "No credentials", "skip"],
      ["unreviewed", "Not declared", "Not declared", "Review in JSON", "Not declared"],
      ["missing-header", "Not declared", "Not declared", "Review in JSON", "Not declared"],
      ["missing-reference", "Not declared", "Not declared", "Review in JSON", "Not declared"],
    ];
    for (const [id, ...cells] of expectedRows) {
      const heading = within(table).getByRole("rowheader", { name: id });
      const row = heading.closest("tr")!;
      expect(within(row).getAllByRole("cell").map(cell => cell.textContent)).toEqual(cells);
    }
    expect(table.outerHTML).not.toMatch(/OWNER_TOKEN|private-keychain-entry|invalid-literal-marker|MISSING_HEADER_REF/);
    expect(authFetch).toHaveBeenCalledTimes(1);
  });

  it("reviews a separate verification credential even when its identity ID matches a case identity", async () => {
    const spec = { ...draft.spec, expected_access: [{ identity_id: "owner", decision: "allow" }],
      write_verification: { identity: { id: "owner", credential: { type: "bearer", value_keychain: "private-verifier-entry" } } } };
    const { authFetch } = await openReview([{ ...draft, spec }]);
    const main = screen.getByRole("table", { name: "Draft identities" });
    expect(main).toHaveTextContent(/owner.*Environment reference.*allow/);
    const verifier = screen.getByRole("region", { name: "Verification identity" });
    expect(verifier).toHaveTextContent("owner");
    expect(verifier).toHaveTextContent("Keychain reference");
    expect(verifier).not.toHaveTextContent(/\ballow\b/i);
    expect(verifier.outerHTML).not.toMatch(/private-verifier-entry|OWNER_TOKEN/);
    expect(authFetch).toHaveBeenCalledTimes(1);
  });

  it("reviews the selected case locally and restores the review after malformed JSON is repaired", async () => {
    const second = { name: "Second draft", spec: { ...draft.spec, id: "second-case",
      identities: [{ ...draft.spec.identities[0], id: "second-identity", role: "viewer" }] } };
    const { authFetch } = await openReview([draft, second]);
    const picker = screen.getByRole<HTMLSelectElement>("combobox", { name: "Case to review" });
    expect(screen.getByRole("table")).toHaveTextContent("owner");
    await userEvent.selectOptions(picker, picker.options[1]);
    expect(screen.getByRole("table")).toHaveTextContent("second-identity");
    expect(screen.getByRole("table")).not.toHaveTextContent("owner");
    const disclosure = screen.getByText("Review draft identities");
    await userEvent.click(disclosure);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await userEvent.click(disclosure);
    expect(await screen.findByRole("table")).toHaveTextContent("second-identity");
    const editor = screen.getByLabelText("Draft cases JSON");
    fireEvent.change(editor, { target: { value: "{" } });
    expect(screen.getByText("Complete the draft JSON to review identities.")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const repaired = [{ ...second, spec: { ...second.spec, identities: [{ id: "repaired", role: "reader" }] } }];
    fireEvent.change(editor, { target: { value: JSON.stringify(repaired) } });
    expect(screen.getByRole("table")).toHaveTextContent("repaired");
    expect(screen.getByRole("table")).toHaveTextContent("reader");
    expect(authFetch).toHaveBeenCalledTimes(1);
  });

  it("preserves edited JSON fields on save and requires confirmation after an edit", async () => {
    const { authFetch } = await openReview([draft]);
    const editor = screen.getByLabelText("Draft cases JSON");
    const save = screen.getByRole("button", { name: "Save reviewed cases" });
    const confirmation = screen.getByRole("checkbox", { name: /I reviewed/ });
    expect(save).toBeDisabled();
    await userEvent.click(confirmation);
    const edited = [{ ...draft, spec: { ...draft.spec, description: "Edited case", extra_review_metadata: { tags: ["keep"] } } }];
    fireEvent.change(editor, { target: { value: JSON.stringify(edited) } });
    expect(confirmation).not.toBeChecked();
    expect(save).toBeDisabled();
    expect(authFetch).toHaveBeenCalledTimes(1);
    await userEvent.click(confirmation);
    await userEvent.click(save);
    expect(authFetch.mock.calls.map(([path, init]) => `${init?.method} ${path}`)).toEqual([previewRoute, reviewedRoute]);
    expect(JSON.parse(String(authFetch.mock.calls[1][1]?.body))).toEqual({ reviewed: true, cases: edited });
  });
});
