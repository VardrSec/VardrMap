import type { AppSession } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type AuthSelection = "github" | "local" | "signed-out";
const selectionKey = (apiUrl: string) => `vardrmap.auth-method:${apiUrl}`;

export function selectAuthMethod(method: AuthSelection, apiUrl = API_URL): void {
  if (typeof window !== "undefined") window.sessionStorage.setItem(selectionKey(apiUrl), method);
}

function selectedMethod(apiUrl: string): AuthSelection | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.sessionStorage.getItem(selectionKey(apiUrl));
    return value === null || value === "github" || value === "local" ? value : "signed-out";
  } catch { return "signed-out"; }
}

export function isSecureApi(apiUrl: string): boolean {
  try { return new URL(apiUrl).protocol === "https:"; } catch { return false; }
}

export function hasWorkspaceSession(session: AppSession | null): boolean {
  return Boolean(session?.backendToken || (session?.authMethod === "local" && session.csrfToken));
}

export function authenticatedOptions(session: AppSession, init: RequestInit, apiUrl = API_URL): RequestInit {
  const headers = new Headers(init.headers || {});
  if (session.authMethod === "local") {
    if (!isSecureApi(apiUrl)) throw new Error("Local authentication requires HTTPS");
    if (!session.csrfToken) throw new Error("Not authenticated");
    headers.delete("Authorization");
    headers.set("X-CSRF-Token", session.csrfToken);
  } else {
    if (!session.backendToken) throw new Error("Not authenticated");
    headers.set("Authorization", `Bearer ${session.backendToken}`);
  }
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return { ...init, headers, ...(session.authMethod === "local" ? { credentials: "include", redirect: "error" } : {}), cache: "no-store" };
}

export async function getFrontendSession(apiUrl = API_URL): Promise<AppSession | null> {
  const selected = selectedMethod(apiUrl);
  if (selected === "signed-out") return null;
  if (selected !== "local") {
    try {
      const response = await fetch("/api/auth/session", { credentials: "include", cache: "no-store" });
      if (!response.ok) return null;
      const data = await response.json();
      if (typeof data?.backendToken === "string" && data.backendToken) {
        selectAuthMethod("github", apiUrl);
        return data;
      }
      if (selected === "github") return null;
    } catch { return null; }
  }
  if (!isSecureApi(apiUrl)) return null;
  try {
    const response = await fetch(`${apiUrl}/auth/local/session`, { credentials: "include", cache: "no-store", redirect: "error" });
    if (!response.ok) return null;
    const data = await response.json();
    if (data?.authMethod !== "local" || typeof data.csrfToken !== "string" || !/^[0-9a-f]{64}$/.test(data.csrfToken)
      || typeof data.user?.githubId !== "string" || !data.user.githubId.startsWith("local:")) return null;
    selectAuthMethod("local", apiUrl);
    return { authMethod: "local", csrfToken: data.csrfToken, user: data.user };
  } catch { return null; }
}
