/** @jest-environment node */
import { authenticatedOptions, getFrontendSession, selectAuthMethod } from "../auth-client";
import { authMethods } from "../../lib/auth-methods";

const csrf = "a".repeat(64);
const local = { authMethod: "local" as const, csrfToken: csrf };
const api = "https://api.example.test";
const fetchMock = jest.fn();

beforeEach(() => {
  global.fetch = fetchMock; fetchMock.mockReset();
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "window", { configurable: true, value: { sessionStorage: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
  } } });
});
afterEach(() => { Reflect.deleteProperty(globalThis, "window"); });

test("GitHub retains its bearer while local cookies require HTTPS and CSRF", () => {
  const github = authenticatedOptions({ backendToken: "github-token" }, {});
  expect(new Headers(github.headers).get("Authorization")).toBe("Bearer github-token");
  const options = authenticatedOptions(local, { method: "POST", headers: { Authorization: "stale" } }, api);
  expect(new Headers(options.headers).get("Authorization")).toBeNull();
  expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(csrf);
  expect(options).toMatchObject({ credentials: "include", redirect: "error", cache: "no-store" });
  expect(() => authenticatedOptions(local, {}, "http://localhost:8000")).toThrow("HTTPS");
  expect(() => authenticatedOptions({ authMethod: "local" }, {}, api)).toThrow("Not authenticated");
});

test("multipart uploads retain the browser-generated boundary", () => {
  const body = new FormData();
  body.append("file", "fixture");
  expect(new Headers(authenticatedOptions(local, { body }, api).headers).has("Content-Type")).toBe(false);
});

test("existing GitHub sessions take precedence without requesting local credentials", async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ backendToken: "github-token" }) });
  expect(await getFrontendSession(api)).toEqual({ backendToken: "github-token" });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("local session metadata never becomes a browser bearer token", async () => {
  fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
  fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ ...local, user: { githubId: "local:fixture", username: "operator" }, backendToken: "must-not-escape" }) });
  expect(await getFrontendSession(api)).toEqual({ ...local, user: { githubId: "local:fixture", username: "operator" } });
  expect(fetchMock).toHaveBeenLastCalledWith(api + "/auth/local/session", expect.objectContaining({ credentials: "include", redirect: "error" }));
});

test("insecure fallback and malformed local identities fail closed", async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
  expect(await getFrontendSession("http://localhost:8000")).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ ...local, user: { githubId: "github-user" } }) });
  expect(await getFrontendSession(api)).toBeNull();
});

test("available authentication methods use explicit validated configuration", () => {
  expect(authMethods("github")).toEqual(["github"]);
  expect(authMethods("local")).toEqual(["local"]);
  expect(authMethods("github, local,github")).toEqual(["github", "local"]);
  for (const value of ["", "local,", "anonymous"]) expect(() => authMethods(value)).toThrow();
});

test.each(["network", "http", "json"])("a GitHub %s failure never selects an existing local identity", async failure => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/auth/session") {
      if (failure === "network") throw new Error("unavailable");
      return { ok: failure !== "http", json: async () => { throw new Error("invalid json"); } };
    }
    return { ok: true, json: async () => ({ ...local, user: { githubId: "local:other" } }) };
  });
  expect(await getFrontendSession(api)).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("a restored GitHub identity stays selected after its session expires", async () => {
  fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ backendToken: "github-token" }) });
  expect(await getFrontendSession(api)).not.toBeNull();
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
  expect(await getFrontendSession(api)).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("explicit local selection overrides a remaining GitHub session and never falls back on expiry", async () => {
  selectAuthMethod("local", api);
  fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ ...local, user: { githubId: "local:chosen" } }) });
  expect((await getFrontendSession(api))?.user?.githubId).toBe("local:chosen");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe(api + "/auth/local/session");
  fetchMock.mockResolvedValue({ ok: false });
  expect(await getFrontendSession(api)).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("sign-out suppresses both cookie identities until a deliberate selection", async () => {
  selectAuthMethod("signed-out", api);
  expect(await getFrontendSession(api)).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("selection is scoped to the configured API and blocked storage fails closed", async () => {
  selectAuthMethod("signed-out", "https://other.example.test");
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ backendToken: "github-token" }) });
  expect(await getFrontendSession(api)).not.toBeNull();
  jest.spyOn(window.sessionStorage, "getItem").mockImplementation(() => { throw new Error("storage blocked"); });
  fetchMock.mockClear();
  expect(await getFrontendSession(api)).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
});
