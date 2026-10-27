import { test, expect, type Page } from "@playwright/test";
import { SignJWT } from "jose";

const api = "https://127.0.0.1:8766";
const originalPassword = "local-browser-fixture-passphrase";
const replacementPassword = "replacement-browser-fixture-passphrase";
const cookieName = "__Host-vardrmap.session";

async function login(page: Page, password: string) {
  await page.getByLabel("Local username").fill("operator");
  await page.getByLabel("Local password").fill(password);
  await page.getByRole("button", { name: "Sign in locally" }).click();
}

test("real HTTPS login, CSRF-protected work, password rotation and logout", async ({ page, context, playwright }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in with GitHub" })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("local-sign-in.png") });
  const providers = await context.request.get("https://127.0.0.1:3007/api/auth/providers");
  expect((await providers.json()).github.id).toBe("github");
  await login(page, originalPassword);
  await expect(page.getByLabel("Active Engagement")).toBeVisible();
  const originalCookie = (await context.cookies(api)).find(cookie => cookie.name === cookieName)!;
  expect(originalCookie).toMatchObject({ secure: true, httpOnly: true, sameSite: "Lax", path: "/" });
  expect(await page.evaluate(() => document.cookie)).not.toContain(cookieName);
  const metadata = await context.request.get(api + "/auth/local/session");
  const profile = await metadata.json();
  expect(profile.authMethod).toBe("local");
  expect(profile.csrfToken).toMatch(/^[0-9a-f]{64}$/);
  expect(profile.backendToken).toBeUndefined();
  expect(profile.user.githubId).toMatch(/^local:/);

  const rejected = await page.evaluate(async url => {
    const response = await fetch(url + "/engagements", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "CSRF must reject", engagement_type: "internal" }),
    });
    return response.status;
  }, api);
  expect(rejected).toBe(403);
  await page.getByLabel("Engagement name").fill("Local authenticated assessment");
  await page.getByLabel("Engagement type").selectOption("internal");
  const created = page.waitForResponse(response => response.url() === api + "/engagements" && response.request().method() === "POST");
  await page.getByRole("button", { name: "Create Engagement", exact: true }).click();
  expect((await created).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByLabel("Active Engagement").locator("option", { hasText: "Local authenticated assessment" })).toHaveCount(1);

  await page.locator("nav").getByRole("button", { name: /Settings$/ }).click();
  await expect(page.getByRole("heading", { name: "Local account password" })).toBeVisible();
  // Real readiness/heartbeat APIs; the create-all SQLite fixture deliberately
  // lacks an Alembic marker and must never appear fully ready.
  const platform = page.getByRole("heading", { name: "Platform and Runner status" }).locator("..");
  const backendStatus = page.getByRole("region", { name: "Backend readiness" });
  await expect(backendStatus.getByText("Not ready", { exact: true })).toBeVisible();
  await expect(platform.getByText("No Runner has reported for this account.")).toBeVisible();
  const heartbeat = await context.request.post(api + "/runner/heartbeat", {
    headers: { Origin: "https://127.0.0.1:3007", "X-CSRF-Token": profile.csrfToken },
    data: { hostname: "browser-fixture-runner", version: "0.51.0", os: "Linux", tools: { httpx: { ok: true, version: "v1.0" } } },
  });
  expect(heartbeat.ok()).toBeTruthy();
  await platform.getByRole("button", { name: "Refresh status" }).click();
  await expect(platform.getByText("Recent report", { exact: true })).toBeVisible();
  await expect(platform.getByText(/Reported version 0.51.0/)).toBeVisible();
  await platform.screenshot({ path: test.info().outputPath("platform-status.png") });
  // Only transport failure is injected here; real Runner data must stay distinct.
  await page.route(api + "/ready", route => route.abort("connectionrefused"));
  await platform.getByRole("button", { name: "Refresh status" }).click();
  await expect(backendStatus.getByText("Unreachable", { exact: true })).toBeVisible();
  await expect(platform.getByText("Recent report", { exact: true })).toBeVisible();
  await page.unroute(api + "/ready");
  await page.screenshot({ path: test.info().outputPath("local-account-settings.png"), fullPage: true });
  await page.getByLabel("Current password").fill(originalPassword);
  await page.getByLabel("New password", { exact: true }).fill(replacementPassword);
  await page.getByLabel("Confirm new password").fill(replacementPassword);
  const changed = page.waitForResponse(response => response.url() === api + "/auth/local/password");
  await page.getByRole("button", { name: "Change password", exact: true }).click();
  expect((await changed).ok()).toBeTruthy();
  await expect.poll(async () => (await context.cookies(api)).find(cookie => cookie.name === cookieName)?.value).not.toBe(originalCookie.value);
  const replay = await playwright.request.newContext({ ignoreHTTPSErrors: true, extraHTTPHeaders: { Cookie: `${cookieName}=${originalCookie.value}` } });
  expect((await replay.get(api + "/auth/local/session")).status()).toBe(401);
  await replay.dispose();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  const rotatedCookie = (await context.cookies(api)).find(cookie => cookie.name === cookieName)!;
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign in locally" })).toBeVisible();
  expect((await context.cookies(api)).find(cookie => cookie.name === cookieName)).toBeUndefined();
  const loggedOut = await playwright.request.newContext({ ignoreHTTPSErrors: true, extraHTTPHeaders: { Cookie: `${cookieName}=${rotatedCookie.value}` } });
  expect((await loggedOut.get(api + "/auth/local/session")).status()).toBe(401);
  await loggedOut.dispose();
  await login(page, originalPassword);
  await expect(page.getByRole("alert").filter({ hasText: "Sign-in failed" })).toBeVisible();
  await login(page, replacementPassword);
  await expect(page.getByLabel("Active Engagement")).toBeVisible();

  // Only this mixed-provider scenario stubs GitHub's session response. The local
  // cookie, JWT verification and all application API requests remain real.
  const mixed = await context.newPage();
  const token = await new SignJWT({ sub: "mixed-github", username: "github-fixture" })
    .setProtectedHeader({ alg: "HS256" }).setIssuer("vardrmap-frontend")
    .setAudience("vardrmap-backend").setExpirationTime("1h")
    .sign(new TextEncoder().encode("browser-fixture-signing-key-only-32-characters"));
  let githubState: "valid" | "failed" | "expired" = "valid";
  await mixed.route("**/api/auth/session", route => githubState === "failed"
    ? route.abort("failed") : route.fulfill({ json: githubState === "expired" ? {} : {
      backendToken: token, user: { githubId: "mixed-github", username: "github-fixture" },
    } }));
  await mixed.goto("/");
  await expect(mixed.getByText("github-fixture", { exact: true })).toBeVisible();
  githubState = "failed";
  await mixed.reload();
  await expect(mixed.getByRole("button", { name: "Sign in locally" })).toBeVisible();
  await expect(mixed.getByLabel("Active Engagement")).toHaveCount(0);
  githubState = "expired";
  await mixed.reload();
  await expect(mixed.getByRole("button", { name: "Sign in locally" })).toBeVisible();
  githubState = "valid";
  await login(mixed, replacementPassword);
  await expect(mixed.getByText("operator", { exact: true })).toBeVisible();
  await mixed.reload();
  await expect(mixed.getByText("operator", { exact: true })).toBeVisible();
  await mixed.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(mixed.getByRole("button", { name: "Sign in locally" })).toBeVisible();
  await expect(mixed.getByLabel("Active Engagement")).toHaveCount(0);
  await mixed.close();
});
