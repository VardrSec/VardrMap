import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// SettingsSection -> ui.tsx -> react-markdown/remark-gfm (ESM); mock so the
// CommonJS jest runtime can import the component.
jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import SettingsSection, { engagementCommands, runnerInitCommand } from "../SettingsSection";

const BASE_ROUTES = {
  "GET /auth/apikeys": { body: { keys: [] } },
  "GET /settings": { body: { webhook_url: "", notify_min_severity: "high" } },
};

describe("SettingsSection workflows", () => {
  it("sets up the runner with the guided init command and no key on the command line", () => {
    const cmd = runnerInitCommand("https://api.example.test");
    expect(cmd).toBe("vardrrunner init --url https://api.example.test --install-service --no-install-tools");
    expect(cmd).not.toContain("--key");
  });

  it("fills engagement commands with the open engagement, or lists engagements first", () => {
    expect(engagementCommands("e-123")).toEqual([
      "vardrrunner scope e-123",
      "vardrrunner run httpx --engagement e-123 --scope",
    ]);
    expect(engagementCommands(null)[0]).toBe("vardrrunner engagements");
  });

  it("shows every setup step with a copy button before a key exists", async () => {
    renderWithApp(<SettingsSection />, {
      routes: BASE_ROUTES,
      overrides: { selectedEngagement: { id: "e-9", name: "Acme API" } as never },
    });
    for (const cmd of [
      "pipx install vardrrunner",
      "vardrrunner tools install --all",
      "vardrrunner doctor",
      "vardrrunner scope e-9",
    ]) {
      expect(await screen.findByText(cmd)).toBeInTheDocument();
    }
    expect(screen.getByText(/Ready for Acme API/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Copy" }).length).toBeGreaterThanOrEqual(7);
  });

  it("shows the key once and keeps it out of every setup command", async () => {
    renderWithApp(<SettingsSection />, {
      routes: { ...BASE_ROUTES, "POST /auth/apikeys": { body: { id: "r1", token: "vmap_runner_secret", label: "" } } },
    });
    await userEvent.click(screen.getByRole("button", { name: "Generate Runner Key" }));
    expect(await screen.findByText("vmap_runner_secret")).toBeInTheDocument();
    const commands = Array.from(document.querySelectorAll("code")).map((el) => el.textContent ?? "");
    const init = commands.find((text) => text.startsWith("vardrrunner init"));
    expect(init).toContain("--install-service");
    for (const text of commands.filter((t) => t.startsWith("vardrrunner"))) {
      expect(text).not.toContain("vmap_runner_secret");
    }
    expect(document.body.textContent).not.toContain("daemon install");
    expect(screen.queryByRole("button", { name: "Download .ps1" })).not.toBeInTheDocument();
  });

  it("shows the PyPI install command before a runner key is generated", async () => {
    renderWithApp(<SettingsSection />, { routes: BASE_ROUTES });
    expect(await screen.findByText("pipx install vardrrunner")).toBeInTheDocument();
    expect(screen.getByText("pipx upgrade vardrrunner")).toBeInTheDocument();
  });

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
