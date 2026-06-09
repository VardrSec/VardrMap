import type { NextConfig } from "next";
import path from "path";

// Pin Turbopack's workspace root to this directory so it doesn't walk up to
// the repo root and pick up the outer package-lock.json, which causes module
// resolution failures in monorepo layouts on Vercel.
const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
