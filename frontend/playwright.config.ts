import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:3006",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${process.env.E2E_PYTHON ?? (process.platform === "win32" ? "../backend/venv/Scripts/python.exe" : "python")}" ../scripts/browser_backend.py`,
      url: "http://127.0.0.1:8765/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3006",
      url: "http://127.0.0.1:3006",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_URL: "http://127.0.0.1:8765",
        VARDRMAP_AUTH_METHODS: "github",
        AUTH_URL: "http://127.0.0.1:3006",
        AUTH_SECRET: "browser-fixture-auth-secret-only-32-characters",
        AUTH_GITHUB_ID: "browser-fixture",
        AUTH_GITHUB_SECRET: "browser-fixture",
        BACKEND_JWT_SECRET: "browser-fixture-signing-key-only-32-characters",
      },
    },
  ],
});
