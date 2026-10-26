import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-local",
  workers: 1,
  retries: 0,
  timeout: 90_000,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "https://127.0.0.1:3007",
    // Only these disposable self-signed fixture origins skip certificate trust.
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${process.env.E2E_PYTHON ?? (process.platform === "win32" ? "../backend/venv/Scripts/python.exe" : "python")}" ../scripts/browser_local_backend.py`,
      url: "https://127.0.0.1:8766/health",
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3007 --experimental-https --experimental-https-key .local-auth-e2e/key.pem --experimental-https-cert .local-auth-e2e/cert.pem",
      url: "https://127.0.0.1:3007",
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_URL: "https://127.0.0.1:8766",
        VARDRMAP_AUTH_METHODS: "github,local",
        AUTH_URL: "https://127.0.0.1:3007",
        AUTH_SECRET: "browser-fixture-auth-secret-only-32-characters",
        AUTH_GITHUB_ID: "browser-fixture",
        AUTH_GITHUB_SECRET: "browser-fixture",
        BACKEND_JWT_SECRET: "browser-fixture-signing-key-only-32-characters",
      },
    },
  ],
});
