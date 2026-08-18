import "@testing-library/jest-dom";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithApp } from "../../../test-utils/renderWithApp";
import ApiSurfaceSection from "../ApiSurfaceSection";

const endpoint = {
  id: "ep-1", program_id: "prog-1", method: "GET", scheme: "https",
  host: "api.example.com", port: null, path_template: "/users/{id}", source: "burp", notes: "",
  observation_count: 2, statuses: [200, 403], identities: ["anonymous", "standard-user"],
  first_seen_at: "2026-08-18T00:00:00Z", last_seen_at: "2026-08-18T00:01:00Z",
};

describe("ApiSurfaceSection", () => {
  it("renders the operation inventory and identity coverage", async () => {
    renderWithApp(<ApiSurfaceSection engagementId="prog-1" />, {
      routes: { "GET /engagements/prog-1/api/endpoints?": { body: { endpoints: [endpoint], total: 1 } } },
    });
    expect(await screen.findByText("/users/{id}")).toBeInTheDocument();
    expect(screen.getByText("200 · 403")).toBeInTheDocument();
    expect(screen.getByText("anonymous, standard-user")).toBeInTheDocument();
  });

  it("loads redacted exchange detail on inspect", async () => {
    renderWithApp(<ApiSurfaceSection engagementId="prog-1" />, {
      routes: {
        "GET /engagements/prog-1/api/endpoints?": { body: { endpoints: [endpoint], total: 1 } },
        "GET /engagements/prog-1/api/endpoints/ep-1": { body: {
          ...endpoint, exchange_total: 1, exchanges: [{
            id: "x-1", endpoint_id: "ep-1", source_tool: "repeater", identity_label: "standard-user",
            request_headers: "Authorization: [REDACTED]", request_body: "", response_headers: "",
            response_body: '{"id":1}', request_hash: "a", response_hash: "b", response_status: 200,
            response_length: 8, response_mime: "application/json", response_time_ms: 42,
            parameter_names: [], note: "", captured_at: null, created_at: null,
          }],
        } },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Inspect" }));
    expect((await screen.findAllByText(/standard-user/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/Authorization: \[REDACTED\]/)).toBeInTheDocument();
  });

  it("explains the manual-promotion empty state", async () => {
    renderWithApp(<ApiSurfaceSection engagementId="prog-1" />, {
      routes: { "GET /engagements/prog-1/api/endpoints?": { body: { endpoints: [], total: 0 } } },
    });
    expect(await screen.findByText("No API exchanges promoted yet.")).toBeInTheDocument();
    expect(screen.getByText(/Automatic capture stays off/)).toBeInTheDocument();
  });
});
