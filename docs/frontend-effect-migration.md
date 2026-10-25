# Legacy effect migration

The frontend dependency upgrade enables React's set-state-in-effect rule. The
existing 21 diagnostics are temporarily warnings in the 15 explicitly listed
legacy component files in frontend/eslint.config.mjs. Other files retain the
recommended error severity; all other lint rules remain enabled.

This is a bounded compatibility measure, not a completed effect refactor. Do not
wrap setters in timers or microtasks to evade diagnostics. Remove file overrides
as their effects are reviewed and fixed in focused changes with behavior tests.

Migration inventory:

- DashboardSection and ReviewSection: consume navigation/prefill events once.
- FindingsSection and ReportsSection: preserve request cancellation and promoted
  data/report prefill consumption without overwriting user edits.
- JobsSection and ScanningSection: preserve engagement changes, pagination,
  provenance filters and selection reset behavior.
- OverviewSection and ProgramSection: preserve form drafts when reviewing which
  prop changes should reset forms; derive values directly where possible.
- FindingActivityPanel, ManualSection, NewEngagementForm, ProposalsPanel,
  ReconSection, ServicesSection and SettingsSection: audit async loaders,
  cancellation, loading state and error handling before moving any state update.

ScanningSection's visible-items filter is now calculated directly during render;
it is a pure bounded filter and requires no manual memoization. This resolves the
new preserve-manual-memoization diagnostic without deferring state updates.

The lint stack is aligned to Next 16.4.3 with ESLint 10. Verify future upgrades
with lint, typecheck, frontend tests and a production build. Keep this inventory
and scoped config in sync; do not expand exceptions to unblock unrelated code.
