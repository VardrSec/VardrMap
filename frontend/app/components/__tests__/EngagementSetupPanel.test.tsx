import "@testing-library/jest-dom";
import { fireEvent, screen, waitFor } from "@testing-library/react";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import type { Engagement } from "../../types";
import EngagementSetupPanel from "../EngagementSetupPanel";

function makeEngagement(over: Partial<Engagement> = {}): Engagement {
  return {
    id: "eng-1", name: "Acme Q3", platform: "", program_url: "",
    scope_summary: "", severity_guidance: "", safe_harbor_notes: "",
    client_id: "", engagement_type: "pentest", engagement_status: "active",
    starts_at: "", ends_at: "",
    scope: { in: [], out: [] }, imports: [],
    recon_count: 0, scans_count: 0, manual_tests_count: 0, findings_count: 0,
    findings_by_severity: {}, findings_by_status: {},
    reports_count: 0, services_count: 0, my_role: "owner",
    ...over,
  };
}

const ok = (body: unknown) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
const fail = () => Promise.resolve({ ok: false, json: () => Promise.resolve({}) });

function setup(engagement: Engagement, handler: (path: string, init?: RequestInit) => Promise<unknown>) {
  const authFetch = jest.fn((path: string, init?: RequestInit) => handler(path, init));
  const setMessage = jest.fn();
  const refreshSelectedEngagement = jest.fn().mockResolvedValue(undefined);
  const onChanged = jest.fn();
  renderWithApp(<EngagementSetupPanel engagement={engagement} onChanged={onChanged} />, {
    overrides: {
      authFetch: authFetch as unknown as never,
      setMessage: setMessage as unknown as never,
      refreshSelectedEngagement: refreshSelectedEngagement as unknown as never,
    },
  });
  return { authFetch, setMessage, refreshSelectedEngagement, onChanged };
}

const calls = (m: jest.Mock, method: string) =>
  m.mock.calls.filter(([, init]) => init?.method === method);

describe("EngagementSetupPanel", () => {
  it("creates a client and links it to the engagement", async () => {
    const { authFetch, setMessage, onChanged } = setup(makeEngagement(), (path, init) => {
      if (path === "/clients" && init?.method === "POST") return ok({ id: "c1", name: "Acme" });
      if (path === "/clients") return ok([]);
      return ok({});
    });
    fireEvent.change(screen.getByLabelText("New client name"), { target: { value: " Acme " } });
    fireEvent.click(screen.getByRole("button", { name: "Save client" }));
    await waitFor(() => expect(setMessage).toHaveBeenCalledWith("Client linked."));
    expect(JSON.parse(calls(authFetch, "POST")[0][1].body)).toEqual({ name: "Acme" });
    expect(JSON.parse(calls(authFetch, "PATCH")[0][1].body)).toEqual({ client_id: "c1" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("links an existing client without creating another", async () => {
    const { authFetch, setMessage } = setup(makeEngagement(), (path) =>
      path === "/clients" ? ok([{ id: "c9", name: "Existing" }]) : ok({}));
    await screen.findByRole("option", { name: "Existing" });
    fireEvent.change(screen.getByLabelText("Client"), { target: { value: "c9" } });
    fireEvent.click(screen.getByRole("button", { name: "Save client" }));
    await waitFor(() => expect(setMessage).toHaveBeenCalledWith("Client linked."));
    expect(calls(authFetch, "POST")).toHaveLength(0);
    expect(JSON.parse(calls(authFetch, "PATCH")[0][1].body)).toEqual({ client_id: "c9" });
  });

  it("refuses to save a client with nothing chosen", async () => {
    const { authFetch, setMessage } = setup(makeEngagement(), () => ok([]));
    fireEvent.click(screen.getByRole("button", { name: "Save client" }));
    await waitFor(() => expect(setMessage).toHaveBeenCalledWith("Choose a client or enter a new client name."));
    expect(calls(authFetch, "PATCH")).toHaveLength(0);
  });

  it("rejects a testing window that ends before it starts", async () => {
    const { authFetch, setMessage } = setup(makeEngagement(), () => ok([]));
    fireEvent.change(screen.getByLabelText("Testing window starts"), { target: { value: "2026-10-27T12:00" } });
    fireEvent.change(screen.getByLabelText("Testing window ends"), { target: { value: "2026-10-27T11:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save testing window" }));
    await waitFor(() => expect(setMessage).toHaveBeenCalledWith("The testing window must end after it starts."));
    expect(calls(authFetch, "PATCH")).toHaveLength(0);
  });

  it("saves a testing window as zone-aware timestamps", async () => {
    const { authFetch, setMessage } = setup(makeEngagement(), () => ok([]));
    fireEvent.change(screen.getByLabelText("Testing window starts"), { target: { value: "2026-10-27T10:00" } });
    fireEvent.change(screen.getByLabelText("Testing window ends"), { target: { value: "2026-10-28T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save testing window" }));
    await waitFor(() => expect(setMessage).toHaveBeenCalledWith("Testing window saved."));
    const body = JSON.parse(calls(authFetch, "PATCH")[0][1].body);
    expect(body.starts_at).toMatch(/Z$/);
    expect(body.ends_at).toMatch(/Z$/);
  });

  it("records an authorization and clears the form", async () => {
    const { authFetch, setMessage, onChanged } = setup(makeEngagement(), () => ok([]));
    fireEvent.change(screen.getByLabelText("Authorized by"), { target: { value: "Target owner" } });
    fireEvent.change(screen.getByLabelText("Reference"), { target: { value: "SOW-1" } });
    fireEvent.change(screen.getByLabelText("Permits"), { target: { value: "API testing" } });
    fireEvent.click(screen.getByRole("button", { name: "Record authorization" }));
    await waitFor(() => expect(setMessage).toHaveBeenCalledWith("Authorization recorded."));
    const [path, init] = calls(authFetch, "POST")[0];
    expect(path).toBe("/engagements/eng-1/authorizations");
    expect(JSON.parse(init.body)).toEqual({ authorized_by: "Target owner", reference: "SOW-1", permits: "API testing" });
    expect(onChanged).toHaveBeenCalled();
    expect(screen.getByLabelText("Authorized by")).toHaveValue("");
  });

  it("requires who authorized the work and what it permits", async () => {
    const { authFetch, setMessage } = setup(makeEngagement(), () => ok([]));
    fireEvent.click(screen.getByRole("button", { name: "Record authorization" }));
    await waitFor(() =>
      expect(setMessage).toHaveBeenCalledWith("Authorization needs who authorized the work and what it permits."));
    expect(calls(authFetch, "POST")).toHaveLength(0);
  });

  it("reports a failed authorization save without clearing the form", async () => {
    const { setMessage } = setup(makeEngagement(), (_path, init) => (init?.method === "POST" ? fail() : ok([])));
    fireEvent.change(screen.getByLabelText("Authorized by"), { target: { value: "Owner" } });
    fireEvent.change(screen.getByLabelText("Permits"), { target: { value: "Testing" } });
    fireEvent.click(screen.getByRole("button", { name: "Record authorization" }));
    await waitFor(() => expect(setMessage).toHaveBeenCalledWith("Failed to record authorization."));
    expect(screen.getByLabelText("Authorized by")).toHaveValue("Owner");
  });

  it("renders nothing for viewers, who cannot write", () => {
    setup(makeEngagement({ my_role: "viewer" }), () => ok([]));
    expect(screen.queryByRole("button", { name: "Record authorization" })).toBeNull();
  });
});
