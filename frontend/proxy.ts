import { randomBytes } from "node:crypto";
import { auth } from "@/auth";
import { NextResponse } from "next/server";

// Keep Auth.js as the existing proxy entrypoint. Only HTML navigations gain
// script-policy reporting; API auth and non-HTML requests behave as before.
export const proxy = auth((request) => {
  if (!request.headers.get("accept")?.includes("text/html")) return;

  const nonce = randomBytes(16).toString("base64");
  const reportOnly = "script-src 'self' 'nonce-" + nonce + "' 'strict-dynamic'";
  const upstream = new Headers(request.headers);
  upstream.set("x-nonce", nonce);
  // Next.js reads a request CSP while noncing its own framework scripts.
  upstream.set("Content-Security-Policy-Report-Only", reportOnly);
  const response = NextResponse.next({ request: { headers: upstream } });
  response.headers.set("Content-Security-Policy-Report-Only", reportOnly);
  // Do not shared-cache per-request nonce-bearing HTML.
  response.headers.set("Cache-Control", "private, no-store");
  return response;
});

export const config = {
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"],
};
