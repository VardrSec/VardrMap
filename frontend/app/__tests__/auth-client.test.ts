/** @jest-environment node */
import { authenticatedOptions, getFrontendSession } from "../auth-client";
import { authMethods } from "../../lib/auth-methods";

const csrf = "a".repeat(64);
const local = { authMethod: "local" as const, csrfToken: csrf };
const api = "https://api.example.test";
const fetchMock = jest.fn();

beforeEach(() => { global.fetch = fetchMock; fetchMock.mockReset(); });

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
