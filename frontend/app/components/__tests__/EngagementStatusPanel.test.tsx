import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";

// AppContext's module graph reaches ReportsSection, which imports react-markdown
// as ESM. Same stubs the other component suites use.
jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }: { children: string }) => children }));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import { renderWithApp } from "../../../test-utils/renderWithApp";
import { AppContext, type AppContextValue } from "../../context/AppContext";
import type { Engagement } from "../../types";
import EngagementStatusPanel from "../EngagementStatusPanel";

/**
 * The bug these cover: switching engagements left the previous engagement's
 * authorization and client on screen, and a slow response from the engagement
 * you just left could overwrite the one you are now looking at. On a panel whose
 * job is to say "are you authorized to test this", showing another client's
 * authorization is the worst possible failure.
 */

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

/** Renders with a caller-supplied fetch so response timing is controllable. */
function renderPanel(engagement: Engagement, authFetch: jest.Mock) {
  const utils = renderWithApp(<EngagementStatusPanel engagement={engagement} />, {
    overrides: { authFetch: authFetch as unknown as never },
  });
  // rerender replaces the whole tree, so the provider has to be re-wrapped —
  // reusing the harness's own context value keeps authFetch stable across the
  // switch, which is exactly what the stale-response tests depend on.
  const switchTo = (next: Engagement) =>
    utils.rerender(
      <AppContext.Provider value={utils.value as unknown as AppContextValue}>
        <EngagementStatusPanel engagement={next} />
      </AppContext.Provider>,
    );
  return { ...utils, switchTo };
}

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = () => ({ ok: false, status: 500, json: async () => ({}) });

function routed(map: Record<string, unknown>, failing: string[] = []) {
  return jest.fn(async (path: string) => {
    if (failing.some((f) => path.includes(f))) return fail();
    const key = Object.keys(map).find((k) => path.includes(k));
    return ok(key ? map[key] : null);
  });
}

const AUTHORIZED = { id: "a-1", reference: "SOW-2026-014" };

// --------------------------------------------------------------------------- #
// Switching engagements
// --------------------------------------------------------------------------- #

it("clears a previous engagement's authorization when switching to one without", async () => {
  const authFetch = jest.fn(async (path: string) => {
    if (path.includes("/eng-1/authorization")) return ok(AUTHORIZED);
    return ok(null); // eng-2 has none
  });

  const first = makeEngagement({ id: "eng-1" });
  const { switchTo } = renderPanel(first, authFetch);
  expect(await screen.findByText(/SOW-2026-014/)).toBeInTheDocument();

  switchTo(makeEngagement({ id: "eng-2" }));

  expect(await screen.findByText(/none on record/i)).toBeInTheDocument();
  // The previous engagement's authorization must be gone, not merely covered.
  expect(screen.queryByText(/SOW-2026-014/)).not.toBeInTheDocument();
});

it("clears a previous engagement's client when switching to one without", async () => {
  const authFetch = routed({
    "/authorization/active": null,
    "/clients/cl-1": { id: "cl-1", name: "Acme Corp" },
  });

  const { switchTo } = renderPanel(
    makeEngagement({ id: "eng-1", client_id: "cl-1" }), authFetch,
  );
  expect(await screen.findByText("Acme Corp")).toBeInTheDocument();

  switchTo(makeEngagement({ id: "eng-2", client_id: "" }));

  await waitFor(() => expect(screen.queryByText("Acme Corp")).not.toBeInTheDocument());
  expect(screen.getByText("Not linked")).toBeInTheDocument();
});

it("clears a client removed from the same engagement", async () => {
  const authFetch = routed({
    "/authorization/active": null,
    "/clients/cl-1": { id: "cl-1", name: "Acme Corp" },
  });

  const { switchTo } = renderPanel(
    makeEngagement({ id: "eng-1", client_id: "cl-1" }), authFetch,
  );
  expect(await screen.findByText("Acme Corp")).toBeInTheDocument();

  // An engagement edit keeps the same id. The client identity still changed,
  // so retaining Acme here would show a relationship that no longer exists.
  switchTo(makeEngagement({ id: "eng-1", client_id: "" }));

  await waitFor(() => expect(screen.queryByText("Acme Corp")).not.toBeInTheDocument());
  expect(screen.getByText("Not linked")).toBeInTheDocument();
});

it("ignores a response that arrives after the engagement changed", async () => {
  // eng-1's request resolves *after* eng-2's — the out-of-order case.
  let releaseFirst: (v: unknown) => void = () => {};
  const firstPending = new Promise((resolve) => { releaseFirst = resolve; });

  const authFetch = jest.fn(async (path: string) => {
    if (path.includes("/eng-1/authorization")) {
      await firstPending;
      return ok({ id: "stale", reference: "STALE-FROM-ENG-1" });
    }
    return ok(null);
  });

  const { switchTo } = renderPanel(makeEngagement({ id: "eng-1" }), authFetch);

  switchTo(makeEngagement({ id: "eng-2" }));
  expect(await screen.findByText(/none on record/i)).toBeInTheDocument();

  // Now let the abandoned request finish. It must not repaint the panel.
  releaseFirst(null);
  await waitFor(() => expect(screen.queryByText(/STALE-FROM-ENG-1/)).not.toBeInTheDocument());
  expect(screen.getByText(/none on record/i)).toBeInTheDocument();
});

it("ignores stale authorization JSON that finishes parsing after a switch", async () => {
  let releaseJson: (v: unknown) => void = () => {};
  const delayedJson = new Promise((resolve) => { releaseJson = resolve; });
  const authFetch = jest.fn(async (path: string) => {
    if (path.includes("/eng-1/authorization")) {
      return {
        ok: true,
        status: 200,
        json: async () => {
          await delayedJson;
          return { id: "stale", reference: "STALE-PARSED-LATE" };
        },
      };
    }
    return ok(null);
  });

  const { switchTo } = renderPanel(makeEngagement({ id: "eng-1" }), authFetch);
  await waitFor(() => expect(authFetch).toHaveBeenCalled());
  switchTo(makeEngagement({ id: "eng-2" }));
  expect(await screen.findByText(/none on record/i)).toBeInTheDocument();

  releaseJson(null);
  await waitFor(() => expect(screen.queryByText(/STALE-PARSED-LATE/)).not.toBeInTheDocument());
  expect(screen.getByText(/none on record/i)).toBeInTheDocument();
});

// --------------------------------------------------------------------------- #
// Failure is not "none"
// --------------------------------------------------------------------------- #

it("distinguishes a failed authorization lookup from no authorization", async () => {
  const authFetch = routed({}, ["/authorization/active"]);
  renderPanel(makeEngagement(), authFetch);

  expect(await screen.findByText(/could not check/i)).toBeInTheDocument();
  // Must not claim the engagement is unauthorized when we simply do not know.
  expect(screen.queryByText(/none on record/i)).not.toBeInTheDocument();
});

it("does not list a missing authorization as a setup gap when the lookup failed", async () => {
  const authFetch = routed({}, ["/authorization/active"]);
  renderPanel(makeEngagement(), authFetch);

  await screen.findByText(/could not check/i);
  expect(screen.queryByText(/no active authorization on record/i)).not.toBeInTheDocument();
});

it("lists a missing authorization as a gap when the lookup succeeded with none", async () => {
  const authFetch = routed({ "/authorization/active": null });
  renderPanel(makeEngagement(), authFetch);

  expect(await screen.findByText(/no active authorization on record/i)).toBeInTheDocument();
});

// --------------------------------------------------------------------------- #
// Loading and steady state
// --------------------------------------------------------------------------- #

it("shows a loading state while checking, and again on switch", async () => {
  let release: (v: unknown) => void = () => {};
  const pending = new Promise((resolve) => { release = resolve; });
  const authFetch = jest.fn(async (path: string) => {
    if (path.includes("/eng-2/authorization")) { await pending; return ok(null); }
    return ok(AUTHORIZED);
  });

  const { switchTo } = renderPanel(makeEngagement({ id: "eng-1" }), authFetch);
  expect(await screen.findByText(/SOW-2026-014/)).toBeInTheDocument();

  switchTo(makeEngagement({ id: "eng-2" }));

  // Immediately on switch: checking, and crucially not the old authorization.
  expect(screen.getByText(/checking/i)).toBeInTheDocument();
  expect(screen.queryByText(/SOW-2026-014/)).not.toBeInTheDocument();

  release(null);
  expect(await screen.findByText(/none on record/i)).toBeInTheDocument();
});

it("shows an active authorization with its reference", async () => {
  const authFetch = routed({ "/authorization/active": AUTHORIZED });
  renderPanel(makeEngagement(), authFetch);
  expect(await screen.findByText(/Active · SOW-2026-014/)).toBeInTheDocument();
});

it("treats bounty work as authorized by programme policy", async () => {
  const authFetch = routed({ "/authorization/active": null });
  renderPanel(makeEngagement({ engagement_type: "bug_bounty" }), authFetch);

  expect(await screen.findByText(/programme policy/i)).toBeInTheDocument();
  expect(screen.queryByText(/none on record/i)).not.toBeInTheDocument();
  // A bounty engagement needs no client either.
  expect(screen.getByText("Not applicable")).toBeInTheDocument();
});

it("surfaces stop-work prominently", async () => {
  const authFetch = routed({ "/authorization/active": AUTHORIZED });
  renderPanel(
    makeEngagement({ stop_work_at: "2026-08-17T10:00:00", stop_work_reason: "client call" }),
    authFetch,
  );
  expect(await screen.findByText(/stop-work engaged/i)).toBeInTheDocument();
  expect(screen.getByText(/client call/)).toBeInTheDocument();
});

it("does not fetch a client when none is linked", async () => {
  const authFetch = routed({ "/authorization/active": null });
  renderPanel(makeEngagement({ client_id: "" }), authFetch);

  await screen.findByText(/none on record/i);
  expect(authFetch).not.toHaveBeenCalledWith(expect.stringContaining("/clients/"));
});
