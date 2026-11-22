# Changelog

## Unreleased

- Review one draft case at a time in the case builder. A read-only summary shows identity and resource context, credential source types, and declared access decisions.

- Show unmatched cases and unattributed assessments in Authorization coverage even before the first operation is captured. Reviewers can page through all captured operations with their selected filter and sort order.

- Show verified authorization decisions alongside HTTP outcomes in coverage and the relationship matrix. Candidate findings link to the exact evidence record, and historical runs with missing proof show as inconclusive.

- Speed up authorization coverage on larger inventories by indexing route templates when matching cases and historical runs.

- Require a completed parent in the same engagement before a dependent job can be claimed.

- Preserve stored service details when a scan re-observes an existing service with missing or empty details (#144).

- Ignore agent-local credential and session files, retaining the existing private-note exclusions and Gitleaks coverage.

- Verify retained OS backport source checksums in both actual runtime images.

- Backport the maintained util-linux mount/descriptor security fixes and their
  header/flag follow-ups, retaining the Trixie ABI and corresponding source.

- Backport the upstream infocmp analysis bound to the existing Trixie ncurses
  source; retain original/modified source without replacing runtime libraries.

- Rebuild the fixed SQLite runtime in both local images using Trixie build
  packages, retaining original/modified source and package copyright material.


## Prepared source versions

- [v0.44.0 — managed authorization and reconciled user guidance](changelog/v0.44.0.md)
  (prepared source version; not a published release).

## Previous releases

Versioned release histories are retained in [changelog/](changelog/).
Historical version headings do not by themselves confirm published tags or artifacts.
