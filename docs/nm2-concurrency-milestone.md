# NM-2 concurrency slice — local review milestone

Independent acceptance pending. Both repositories use isolated
`codex/nm2-concurrency-budget` branches: Map from accepted `45d4286190039462b942a69615214d6e480fb0ee`,
Runner from accepted `7a5177d2d486fc35b91afc8a96fb1240e9d99fcf`.
No publication, retained environment, distribution pin or roadmap change.

Implemented owner/full-scope explicit engagement policy, transactional reservation
with owned claim, required Runner opt-in/receipt, confirmed terminal release at
most once, held uncertainty/cancellation/expiry, and policy/deletion guards.
See [scope, protocol and rollback limits](nm2-concurrency-budget.md).

Validation:

- Full native Runner: 1,912 passed, 10 skipped, 95.79% coverage; focused API/CLI/
  controlled set 191 passed. Required Ruff lint/format, mypy and medium/high Bandit
  checks passed. No process/Gate/grant semantics changed in this slice.
- Full PostgreSQL backend: 1,265 passed, one skipped, one documentation route-name
  failure. Corrected exact path; final affected documentation/policy set: 20 passed.
- Production-dialect migration/control/capacity set: 16 passed and two rollback
  wording assertions failed; restored the established verified-backup guidance,
  then both affected rollback tests passed. Downgrade still refuses deletion and
  preserves credentials, accounting and migration head. No safety relaxation.
- Final capacity races: two passing administrator/restricted-role cases, each
  exercising 20 competing claims, 10 enable races, 10 disable races, duplicate
  finishes and separate-engagement isolation. Final backend capacity set: 10 passed,
  including role/key/foreign denials, explicit malformed-policy refusal and held
  cancellation/expiry/uncertainty. Both ephemeral PostgreSQL clusters stopped.

Other corrected failures: audit action exceeded PostgreSQL varchar(20), so use a
shorter action without changing the schema; member creation fixture expected 200
instead of established 201; initial SQLite absolute database URL was rejected by
the test safety guard, so reran from a disposable directory with the required
`vardrmap_test*` name. No retained database was used. Full tests are reported as
observed, with affected corrective reruns rather than a fabricated clean full run.

The machine-readable receipt outside Git binds exact review commits and artifact
hashes, including failures/corrections and prior immutable evidence. PostgreSQL
used newly generated disposable certificates, hostname-verified TLS and SCRAM;
no service, TLS bypass, retained secrets or Docker volume changes.

Limits: count trusted owned attempts only, not arbitrary manual processes or RPS.
Runner confirmation is not independent OS attestation. Unknown attempts can hold
capacity indefinitely; there is deliberately no unsafe force release. Policy
changes require idle state. Target/duration budgets, managed signed approval,
runtime/connectivity/restart gates and the opt-in least-privilege worker remain
open. Linux/Docker and ffuf controlled execution are unsupported. Whole NM-2,
NM-3, public/VPN/fresh-host and release gates are not closed by this increment.
