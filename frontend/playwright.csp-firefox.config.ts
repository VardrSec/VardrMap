import { defineConfig, devices } from "@playwright/test";
import chromiumConfig from "./playwright.config";

// Reuse the same disposable servers but run only the focused CSP/login
// smoke in Firefox, without changing the default Chromium acceptance suite.
export default defineConfig({
  ...chromiumConfig,
  projects: [{ name: "firefox", use: { ...devices["Desktop Firefox"] } }],
});
