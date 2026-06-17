import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// SettingsSection -> ui.tsx -> react-markdown/remark-gfm (ESM); mock so the
// CommonJS jest runtime can import the component.
jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import SettingsSection from "../SettingsSection";

const BASE_ROUTES = {
  "GET /auth/apikeys": { body: { keys: [] } },
  "GET /settings": { body: { webhook_url: "", notify_min_severity: "high" } },
};

describe("SettingsSection workflows", () => {
  it("loads and renders existing API keys on mount", async () => {
    renderWithApp(<SettingsSection />, {
      routes: {
        ...BASE_ROUTES,
        "GET /auth/apikeys": { body: { keys: [{ id: "k1", label: "Burp Suite", created_at: null }] } },
      },
    });
    expect(await screen.findByText("Burp Suite")).toBeInTheDocument();
  });

  it("generates a key (POST /auth/apikeys) and shows the one-time token", async () => {
    const { authFetch } = renderWithApp(<SettingsSection />, {
      routes: { ...BASE_ROUTES, "POST /auth/apikeys": { body: { id: "k2", token: "vmap_secret", label: "" } } },
    });
    await userEvent.click(screen.getByRole("button", { name: "Generate Key" }));
    expect(await screen.findByText("vmap_secret")).toBeInTheDocument();
    expect(authFetch).toHaveBeenCalledWith("/auth/apikeys", expect.objectContaining({ method: "POST" }));
  });

  it("revokes a key (DELETE /auth/apikeys/:id) and reports it", async () => {
    const { authFetch, setMessage } = renderWithApp(<SettingsSection />, {
      routes: {
        ...BASE_ROUTES,
        "GET /auth/apikeys": { body: { keys: [{ id: "k1", label: "Old", created_at: null }] } },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith("/auth/apikeys/k1", expect.objectContaining({ method: "DELETE" })),
    );
    expect(setMessage).toHaveBeenCalledWith("API key revoked.");
  });

  it("saves notification settings via PATCH /settings", async () => {
    const { authFetch } = renderWithApp(<SettingsSection />, { routes: BASE_ROUTES });
    await userEvent.click(screen.getByRole("button", { name: "Save Notifications" }));
    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith("/settings", expect.objectContaining({ method: "PATCH" })),
    );
  });
});
