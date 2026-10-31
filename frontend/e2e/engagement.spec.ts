import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import { SignJWT } from "jose";
import { createHash } from "node:crypto";

const api = "http://127.0.0.1:8765";
const secret = new TextEncoder().encode("browser-fixture-signing-key-only-32-characters");

async function identity(user: string, expired = false) {
  const token = await new SignJWT({ sub: user, username: user, email: `${user}@example.test` })
    .setProtectedHeader({ alg: "HS256" }).setIssuer("vardrmap-frontend")
    .setAudience("vardrmap-backend").setExpirationTime(expired ? "-1h" : "1h").sign(secret);
  return { token, headers: { Authorization: `Bearer ${token}` } };
}

async function session(page: Page, user: string, token: string) {
  // Only the browser's session response is stubbed. All application API requests
  // go through real JWT verification and the real backend. OAuth remains separate.
  await page.route("**/api/auth/session", route => route.fulfill({ json: {
    user: { githubId: user, username: user, email: `${user}@example.test` },
    backendToken: token, expires: new Date(Date.now() + 3_600_000).toISOString(),
  } }));
}

async function post(request: APIRequestContext, path: string, headers: Record<string, string>, data: unknown) {
  const response = await request.post(api + path, { headers, data });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

test("unauthenticated browser presents GitHub login", async ({ page }) => {
  await page.route("**/api/auth/session", route => route.fulfill({ json: {} }));
  const response = await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in with GitHub" })).toBeVisible();
  await expect(page.getByLabel("Active Engagement")).toHaveCount(0);
  // The page itself, not only the API, refuses framing and MIME sniffing.
  const headers = response!.headers();
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  // Existing enforced framing protection remains. Script policy is report-only.
  expect(headers["cache-control"]).toContain("no-store");
  const reportOnly = headers["content-security-policy-report-only"];
  expect(reportOnly).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
  expect(reportOnly.match(/'nonce-([^']+)'/)?.[1]).toBeTruthy();
  expect(await page.locator("script[nonce]").count()).toBeGreaterThan(0);
  const reloaded = await page.reload();
  expect(reloaded).not.toBeNull();
  expect(reloaded!.headers()["content-security-policy-report-only"]).not.toBe(reportOnly);
  await expect(page.getByRole("button", { name: "Sign in with GitHub" })).toBeVisible();
});

test("API playbook, partial assessment and evidence linking use the real backend", async ({ page, request }) => {
  const user = "browser_api_operator";
  const { token, headers } = await identity(user);
  await post(request, "/auth/sync", headers, {});
  const engagement = await post(request, "/engagements", headers, { name: "Browser API provenance", engagement_type: "internal" });
  const base = `/engagements/${engagement.id}`;
  const spec = { id: "browser-ownership", identities: [
    { id: "owner", credential: { type: "bearer", value_env: "FIXTURE_OWNER" } },
    { id: "other", credential: { type: "bearer", value_env: "FIXTURE_OTHER" } },
  ], request: { method: "GET", url: "https://api.example.test/objects/42" }, expected_access: [
    { identity_id: "owner", decision: "allow" }, { identity_id: "other", decision: "deny" },
  ] };
  const stored = await post(request, base + "/test-cases", headers, { name: "Ownership", spec });
  const job = await post(request, base + "/jobs", headers, { tool_type: "vardrgate_api_test", target_source: "scope", config: { test_case_id: stored.id } });
  await post(request, `/jobs/${job.id}/claim`, headers, {});
  const canonical = (value: unknown): unknown => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, canonical(v)])) : value;
  const caseHash = createHash("sha256").update(JSON.stringify(canonical(spec))).digest("hex");
  // Synthetic result exercises storage and UI. Real execution is tested by the
  // separate loopback Map -> Runner -> Gate acceptance harness.
  await post(request, `/jobs/${job.id}/upload`, headers, { test_case_id: spec.id, case_hash: caseHash, findings: [], executions: [
    { identity_id: "owner", status_code: 200, observed_outcome: "allow" },
    { identity_id: "other", status_code: 503, observed_outcome: "server_error" },
  ] });
  expect((await request.patch(api + `/jobs/${job.id}`, { headers, data: { status: "done" } })).ok()).toBeTruthy();
  await post(request, base + "/findings", headers, { title: "Operator reviewed finding", severity: "high" });
  await session(page, user, token);
  await page.goto("/");
  await page.getByLabel("Active Engagement").selectOption(engagement.id);
  await expect(page.getByText("Assessment: partial", { exact: true })).toBeVisible();
  await page.getByText("vardrgate_api_test", { exact: true }).click();
  await expect(page.getByText(/Job completion alone/)).toBeVisible();
  await expect(page.getByText("1 evaluated · 1 inconclusive · 0 missing · 0 skipped · 0 unexpected executions")).toBeVisible();
  await expect(page.getByText(`Case: ${spec.id} · Identity: other`)).toBeVisible();
  await page.getByRole("button", { name: "Link evidence to a finding" }).click();
  await page.getByLabel("Finding for selected evidence").selectOption({ label: "Operator reviewed finding" });
  const linked = page.waitForResponse(r => r.url().endsWith("/link") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Link this evidence", exact: true }).first().click();
  const proof = await (await linked).json();
  expect(proof.job_id).toBe(job.id);
  expect(proof.case_id).toBe(stored.id);
  expect(proof.identity_id).toBeTruthy();
  await expect(page.getByText(`Linked finding: ${proof.finding_id}`)).toBeVisible();
  await page.locator("nav").getByRole("button", { name: /Review$/ }).click();
  await page.getByRole("button", { name: "API Surface", exact: true }).click();
  await page.getByRole("button", { name: "Show API playbooks" }).click();
  await expect(page.getByText("API-01 · version 1.0")).toBeVisible();
  await page.getByLabel("API playbook").selectOption("API-03");
  await expect(page.getByText("API-03 · version 1.0")).toBeVisible();
  await expect(page.getByText(/Historical or manual records without provenance/)).toBeVisible();
});

test("pentest creation, job preview/queue, candidate review and immutable client report", async ({ page, request }) => {
  const user = "browser_operator";
  const { token, headers } = await identity(user);
  await post(request, "/auth/sync", headers, {});
  const client = await post(request, "/clients", headers, { name: "Browser Fixture Client" });
  await session(page, user, token);
  await page.goto("/");
  await page.getByLabel("Engagement name").fill("Browser API assessment");
  await expect(page.getByLabel("Engagement type")).toHaveValue("pentest");
  await page.getByLabel("Client", { exact: true }).selectOption(client.id);
  const created = page.waitForResponse(r => r.url() === api + "/engagements" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Create Engagement", exact: true }).click();
  const engagement = await (await created).json();
  expect(engagement.engagement_type).toBe("pentest");
  expect(engagement.client_id).toBe(client.id);
  const base = `/engagements/${engagement.id}`;
  // Scope and written authorization are recorded through the interface, not the API.
  const local = (ms: number) => {
    const d = new Date(Date.now() + ms), pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  await page.getByLabel("Active Engagement").selectOption(engagement.id);
  await page.locator("nav").getByRole("button", { name: /Scope$/ }).click();
  await page.getByText("Value", { exact: true }).first().locator("xpath=following-sibling::input").fill("http://127.0.0.1:9876/api?view=full&include=roles");
  await page.getByText("Kind", { exact: true }).first().locator("xpath=following-sibling::input").fill("url");
  const scoped = page.waitForResponse(r => r.url() === api + base + "/scope/in" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Add In-Scope Asset", exact: true }).click();
  expect((await scoped).ok()).toBeTruthy();
  await page.locator("nav").getByRole("button", { name: /Overview$/ }).click();
  await page.getByLabel("Authorized by").fill("Fixture owner");
  await page.getByLabel("Reference").fill("Synthetic browser fixture");
  await page.getByLabel("Permits").fill("Loopback test only");
  await page.getByLabel("Authorization window starts").fill(local(-3_600_000));
  await page.getByLabel("Authorization window ends").fill(local(3_600_000));
  const authorized = page.waitForResponse(r => r.url() === api + base + "/authorizations" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Record authorization", exact: true }).click();
  expect((await authorized).status()).toBe(201);
  await page.reload();
  await page.getByLabel("Active Engagement").selectOption(engagement.id);
  // The tool list starts collapsed to the chosen tool; open it to pick another.
  await page.getByRole("button", { name: /^Tools/ }).click();
  await page.getByRole("button", { name: "Select httpx", exact: true }).click();
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(page.getByText("http://127.0.0.1:9876/api?view=full&include=roles", { exact: true }).first()).toBeVisible();
  const queued = page.waitForResponse(r => r.url() === api + base + "/jobs" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Queue Job", exact: true }).click();
  expect((await (await queued).json()).status).toBe("pending");
  // This browser suite tests queueing, not scanner execution (the separate
  // three-repository acceptance suite runs the actual Runner and Gate).
  const imported = await request.post(api + base + "/imports", { headers, multipart: {
    tool_type: "nuclei", file: { name: "fixture.jsonl", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({
      "template-id": "browser-authorization-fixture", "matched-at": "http://127.0.0.1:9876/users/42",
      info: { name: "Fixture ownership candidate", severity: "high", description: "Synthetic candidate requiring operator review." },
    })) },
  } });
  expect(imported.ok(), await imported.text()).toBeTruthy();
  await page.locator("nav").getByRole("button", { name: /Review$/ }).click();
  await page.getByRole("button", { name: /^Scans/ }).click();
  await expect(page.getByText("Fixture ownership candidate", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Promote →", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Add Finding", exact: true }).locator("..").locator("input").first()).toHaveValue("Fixture ownership candidate");
  const findingSaved = page.waitForResponse(r => r.url() === api + base + "/findings" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Save Finding", exact: true }).click();
  expect((await findingSaved).ok()).toBeTruthy();
  const findings = await request.get(api + base + "/findings", { headers });
  const rows = (await findings.json()).findings;
  expect(rows).toHaveLength(1);
  await page.locator("nav").getByRole("button", { name: /Reports$/ }).click();
  await page.getByRole("button", { name: "New engagement report", exact: true }).click();
  await page.getByLabel("Engagement report title").fill("Browser assessment report");
  await page.getByLabel("Executive summary").fill("Controlled fixture: candidate manually promoted for test purposes.");
  await page.getByLabel("Limitations").fill("Synthetic local test; does not assess a real client.");
  const saved = page.waitForResponse(r => r.url() === api + base + "/deliverables" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Create revision 1", exact: true }).click();
  const revision = await (await saved).json();
  expect(revision.snapshot.findings).toHaveLength(1);
  expect(revision.snapshot.authorizations).toHaveLength(1);
  await expect(page.getByRole("button", { name: "Download Markdown" })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download Markdown" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.md$/);
  await post(request, base + "/findings", headers, { title: "Later finding", severity: "low" });
  const original = await request.get(api + base + `/deliverables/${revision.deliverable_id}/revisions/1`, { headers });
  expect(await original.json()).toEqual(revision);
});

test("viewer reads shared findings, cannot write, and loses access after revocation", async ({ page, request }) => {
  const owner = await identity("browser_share_owner");
  const viewer = await identity("browser_viewer");
  await post(request, "/auth/sync", owner.headers, {});
  await post(request, "/auth/sync", viewer.headers, {});
  const engagement = await post(request, "/engagements", owner.headers, { name: "Shared browser assessment", engagement_type: "internal" });
  const base = `/engagements/${engagement.id}`;
  await post(request, base + "/findings", owner.headers, { title: "Shared verified issue", severity: "high" });
  await post(request, base + "/members", owner.headers, { github_id: "browser_viewer", role: "viewer" });
  await session(page, "browser_viewer", viewer.token);
  await page.goto("/");
  await expect(page.getByLabel("Active Engagement").locator("option", { hasText: engagement.name })).toHaveCount(1);
  await page.getByLabel("Active Engagement").selectOption(engagement.id);
  await page.locator("nav").getByRole("button", { name: /Findings$/ }).click();
  await expect(page.getByText("Shared verified issue", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save Finding", exact: true })).toHaveCount(0);
  const denied = await request.post(api + base + "/findings", { headers: viewer.headers, data: { title: "Forbidden", severity: "low" } });
  expect(denied.status()).toBe(403);
  const revoked = await request.delete(api + base + "/members/browser_viewer", { headers: owner.headers });
  expect(revoked.ok()).toBeTruthy();
  expect((await request.get(api + base, { headers: viewer.headers })).status()).toBe(404);
  await page.reload();
  await expect(page.getByLabel("Active Engagement").locator("option", { hasText: engagement.name })).toHaveCount(0);
});

test("expired backend identity gives a visible session expiry", async ({ page }) => {
  const { token } = await identity("browser_expired", true);
  await session(page, "browser_expired", token);
  await page.goto("/");
  await expect(page.getByText("Session expired. Please sign in again.", { exact: true })).toBeVisible();
});
