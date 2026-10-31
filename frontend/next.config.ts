import type { NextConfig } from "next";
import path from "path";

// Sent with every page and asset, in Compose and on Vercel. None of these limits
// which scripts, styles or connections the app may use, so Next.js rendering and
// the sign-in redirects are unaffected; a script-src policy needs per-request
// nonces and is a separate change. The API sets its own stricter headers.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'" },
];

// Pin Turbopack's workspace root to this directory so it doesn't walk up to
// the repo root and pick up the outer package-lock.json, which causes module
// resolution failures in monorepo layouts on Vercel.
const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
