import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Bounded legacy migration; see docs/frontend-effect-migration.md.
  {
    files: [
      "app/components/DashboardSection.tsx",
      "app/components/FindingActivityPanel.tsx",
      "app/components/FindingsSection.tsx",
      "app/components/JobsSection.tsx",
      "app/components/ManualSection.tsx",
      "app/components/NewEngagementForm.tsx",
      "app/components/OverviewSection.tsx",
      "app/components/ProgramSection.tsx",
      "app/components/ProposalsPanel.tsx",
      "app/components/ReconSection.tsx",
      "app/components/ReportsSection.tsx",
      "app/components/ReviewSection.tsx",
      "app/components/ScanningSection.tsx",
      "app/components/ServicesSection.tsx",
      "app/components/SettingsSection.tsx",
    ],
    rules: { "react-hooks/set-state-in-effect": "warn" },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
