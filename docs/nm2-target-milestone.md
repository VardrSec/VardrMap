# NM-2 target slice — local review milestone

Independent acceptance pending. Map and Runner use isolated
`codex/nm2-target-budget` branches from accepted concurrency commits
`baf07490674dad9fd0641d39ab0341e4c8ce6d0f` and
`fd61930b29b7a58fcf5dfad73e3b66ca95f0aea8`, respectively. Prior branches, evidence,
roadmap, distribution and pins are preserved. No publication or retained-state
changes. See [the measured unit and protocol](nm2-target-budget.md).

Implemented explicit cumulative represented-origin-attempt policy, durable spend
charged with a successful owned claim, exact unresolved case/origin receipt
binding, fixed Gate guard enforcement and no refunds/reset paths. Setup, resource,
all preflights, verification and reset origins are conservatively included.
Default/manual behavior stays unchanged for unconfigured engagements. Unsupported
profiles refuse. Normalized effective execution settings match the compiled guard.

## Final validation

| Check | Result |
|---|---|
| Full native Runner | 1,921 passed, 10 skipped; 95.81% coverage. Required Ruff lint/format including container, mypy and Bandit medium/high checks passed. |
| Full PostgreSQL backend | 1,278 passed, one skipped; four existing dependency deprecation warnings. No final backend failures. |
| Production-dialect budget/migration set | 18 passed, 10 unrelated deselected. Includes administrator/restricted roles, additive head/startup and safe downgrade refusal, preserved concurrency accounting and target races. |
| Target races, each role | 20 competing same-engagement claims, duplicate finishes, deletion/reconfiguration spend preservation; actual separate-engagement claims/receipts with the exhausted first engagement rechecked; 10 enable-versus-legacy and 10 disable-versus-bound claim races. |
| Real Map HTTP → Runner → native guarded Gate | 14 requests over all five phases; original case hash preserved; one origin charged; second exhausted attempt produced zero additional traffic. Concurrency and expiring grants were enabled together. No managed signed approval claim. |

Initial narrower PostgreSQL target cases and affected backend tests also passed
(two role cases and 29 backend checks). They were expanded after independent
review found that checking a second engagement's zero counter did not demonstrate
independent execution. Final evidence uses actual separate claims and policy races.
No product defect was found by those expanded concurrency checks.

## Corrected failures

- The initial real integration fixture lacked test-only Typer in Map's environment.
  The fixture reuses existing Runner test packages without installing anything or
  altering either environment.
- A real guarded queue execution exited before dispatch because its effective
  settings were not normalized to match the projection. The opted-in path now
  passes `plan.execution`, as the existing standalone adapter does. A lifecycle
  regression verifies both projection and settings, and the real fixture passes.
- Initial type checking found heterogeneous optional claim kwargs needed explicit
  typing; corrected without changing default HTTP payloads.

The unchanged Gate binary is the existing native fixture build from `e99714b`,
SHA-256 `2a89debd92eb30385da0b2949061cdd02cb5399cf5435adecc98e214eb6f55c0`.
PostgreSQL used disposable certificates, hostname-verified TLS/SCRAM and temporary
administrator/restricted schemas. All created clusters stopped. No Docker service,
volume, retained secret/database or installation was changed. The external local
receipt binds exact commits, test/fixture logs, failed/corrected evidence and prior
immutable milestone hashes.

## Limits and open gates

The allowance measures admitted represented-origin attempts, not actual contacts:
even a known prelaunch failure after claim receives no refund. It does not count
ordinary manual tools, DNS/proxy connections, unique IPs or RPS. Existing trusted
Runner/account permissions remain part of the boundary. Metadata is authenticated
owned protocol evidence, not signed execution approval or independent OS proof.
Deletion/disable of spent engagements is intentionally refused; no force reset is
provided. Idle explicit ceiling changes preserve spent.

Duration budgets, managed signed approval, runtime/connectivity/restart acceptance
and the opt-in least-privilege worker remain mandatory subsequent work. Linux/
Docker and ffuf controlled execution remain unsupported. No NM-2 phase closure,
NM-3, fresh-host/public/VPN certification, risk acceptance or release is implied.
