# NM-2 duration-allocation slice — local review milestone

Independent acceptance pending. Both repositories use isolated
`codex/nm2-duration-budget` branches, from accepted target commits Map
`4c6bc644cacc116cd7020bc12afe3fb6cf691375` and Runner
`1824c8343bb74b33630cfd4d82bade65d3d3c6c6`. Prior branches, immutable evidence,
personal roadmap and distribution/pins are preserved. No publication/deployment
or retained environment change. See [the exact unit and boundary](nm2-duration-budget.md).

Implemented explicit owner/full-scope policy, atomic nonrefundable finite allocation
with owned claim, bound receipt checks, immutable claim-start monotonic permission
and strictest-limit composition through existing launch/supervision checks.
Configuration/deletion cannot erase allocated total; unknown and terminal outcomes
never refund it. Defaults and independent target/concurrency/grant controls remain.

## Final checks

| Check | Observed result |
|---|---|
| Full native Runner | 1,946 passed, 10 skipped; 95.81% coverage. Required lint/format including container, mypy and medium/high Bandit passed. |
| Full PostgreSQL backend | 1,289 passed, one skipped; four existing dependency deprecation warnings. |
| PostgreSQL budget/migration set | 20 passed, 10 unrelated deselected. Includes new head/startup/downgrade refusal and preserved earlier budget behavior. |
| Duration races per database role | 20 competing allocations, 20 actual separate-engagement claims, duplicate claims/finishes, persisted unknown/terminal/deletion accounting, 10 enable-versus-legacy and 10 disable-versus-bound races. Administrator and restricted application roles passed. |
| Real four-control Gate path | Map HTTP → native Runner → guarded Gate with target, concurrency, duration and expiring grants: 14 requests over five phases, preserved case hash, allocated 5 seconds, zero additional traffic from duration exhaustion. Target ceiling was 2; second target charge rolled back to 1 when duration refused. |
| Real owner crash | Claimed Runner owner exited 7 with an active native parent/child tree. Both stopped; both partial files remained. Map retained 5 allocated seconds, uncertainty and no termination acknowledgement; a reloaded journal deferred recovery. No scanner/external target. |

The successful four-control fixture's full first execution took 0.528 seconds,
including transport/finalization; this is an observed fixture duration, not measured
budget consumption or a promised total-job bound. The real crash fixture measured
0.943 seconds from owner process start until verified tree exit, also not a usage
attestation. The unchanged Gate build is source `e99714b`, SHA-256
`2a89debd92eb30385da0b2949061cdd02cb5399cf5435adecc98e214eb6f55c0`.

## Measured native boundary

Final synthetic process fixtures use one-second strictest permission with the
existing default shutdown policy. Rounded observations, in seconds:

| Case | Claim/preparation | Process runtime to stop request | Cleanup to verified stop | Request start to verified stop |
|---|---:|---:|---:|---:|
| Cooperative budget expiry | 0.008 | 1.006 | 0.051 | 1.065 |
| Refusing tree, forced cleanup | 0.006 | 1.008 | 2.071 | 3.085 |
| Earlier per-job timeout | 0.006 | 1.008 | 0.051 | 1.065 |
| Earlier signed deadline | 0.006 | 1.009 | 0.051 | 1.065 |

Both native processes stopped and partial evidence remained in each case.
Separate preparation/permit/grant-lock delays measured 1.153/1.151/1.299 seconds
against a one-second allocation and produced zero process creation. Tests also
cover receipt mismatch, invalid quantities, late claim responses, clock changes
and nested deadlines without renewal. Measurements assume responsive OS/storage;
they do not establish universal timing bounds.

## Corrections and evidence

- Initial type checking exposed heterogeneous optional kwargs and insufficient
  receipt-value narrowing. Corrected types; no threshold or security relaxation.
- Independent source review found explicit duration could be dropped by library
  entry calls without control. Both execution entries now refuse before network/
  process activity; six regressions cover both entries and invalid requests.
- Initial affected Runner set passed 230 tests; corrected-entry/native set passed
  183; final full suite includes all corrections. Initial PostgreSQL duration role
  cases and affected backend set passed 2 and 41 tests before final expansion.
  No final runtime, backend or migration failures remain.

External local evidence binds exact review commits, checks, observations, fixture
sources/logs and prior immutable receipt hashes. Disposable PostgreSQL used fresh
certificates with hostname-verified TLS/SCRAM; every created cluster stopped. The
crash fixture uses synthetic credentials and isolated config, identity, journal
and database. No test used retained installations, secrets, databases or volumes.

## Remaining limits and gates

The ceiling is cumulative allocation of finite permission seconds, not actual
consumed time, CPU or arbitrary manual work. Preclaim work and post-tool artifact
transport/finalization are excluded. Existing cleanup may add two seconds grace
plus two seconds verification and polling/OS/I/O latency; tools may emit traffic
during grace. Blocked preparation may finish late but cannot launch afterward.
No universal hard total duration/network cutoff is claimed.

General managed signed approval, runtime/connectivity/restart acceptance and the
least-privilege opt-in worker remain mandatory open gates. The narrow crash/journal
fixture does not close them. Linux/Docker and ffuf controlled execution remain
unsupported. No whole-NM-2, NM-3, deployment, risk waiver or release is implied.
