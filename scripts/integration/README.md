# Local API engagement acceptance

Run with the VardrMap backend Python environment, a VardrRunner environment with
its dependencies installed, Git and Go (matching VardrGate's `go.mod`). From the
VardrMap checkout on Windows:

```powershell
backend/venv/Scripts/python.exe scripts/integration/run.py --runner ../VardrRunner --gate ../VardrGate --runner-python ../VardrRunner/venv/Scripts/python.exe
```

Use `--go /path/to/go` for a compiler outside PATH and `--output /scratch/path`
to select the parent artifact directory. The harness snapshots tracked and
unignored new files, including current local edits, into a fresh directory. It
records source hashes, builds Gate there, starts a real backend with a new SQLite
database, and exercises the real Runner worker against a loopback API fixture.
It requires no production credentials and stops its HTTP servers on completion.
Go may download dependencies during the build. Artifacts are retained for review.

The worker redirects only local configuration/run/journal paths to scratch. It
does not translate job IDs, normalize result payloads or copy evidence. Private
target access is enabled through the documented operator environment setting;
separate cases verify that the default still blocks loopback. The harness acts
as the operator to review cases, promote findings, link evidence and record
retests; it does not assert that these are automatic product decisions.

Checks cover vulnerable/fixed object authorization, tenant and anonymous access,
admin authorization, credential redaction, evidence hashes and provenance,
reviewed evidence linking, immutable deliverable revisions, stop-work/release,
unreachable targets, empty-result uploads and persisted worker telemetry.
Any failed assertion or harness error returns a nonzero exit code.

For PostgreSQL, set `INTEGRATION_DATABASE_URL` to an **empty disposable database**
whose name starts with `vardrmap_test`, then add `--postgres`. The harness refuses
a nonempty database, runs the complete Alembic chain, and starts the backend with
`ENV=staging` so `create_all` cannot hide migration defects. Both modes initialize
the fixture user through `/auth/sync`, matching the normal browser bootstrap.
PostgreSQL connections use UTC and require TLS by default; `?sslmode=disable` is
available for a local disposable instance without TLS.

CI runs PostgreSQL backend/migration checks and this three-product check using
companion repository commits pinned in `.github/workflows/ci.yml`. Update those
pins deliberately when validating a newer combined stack. Local runs continue
to snapshot the supplied checkouts, including uncommitted changes.

Additional controlled cases cover HTTP 200 body denials, declared hidden-object
404 denials, fixed privileged functions, expired target credentials, two reviewed
collection pages, literal parameter transport, 429/503 responses and redirects.
The target serves only loopback and the run asserts a 100-request ceiling. The
parameter injection canary is a transport check, not an injection detection claim.
Ambiguous HTTP outcomes retain evidence even when the command job completes;
`done` and zero findings are not proof of a clean authorization assessment.
Checks also assert conclusive/partial/inconclusive assessment states, claim-time case
binding, and structured job/case/identity provenance. The real Runner adds the hash
to Gate's artifact; legacy unbound uploads cannot establish a conclusive assessment.

This supplements the repositories' normal suites. The separate
[browser suite](../../docs/development.md#browser-acceptance) exercises real UI
and API persistence; neither suite tests real GitHub OAuth.

## Hosted staging boundary

The automated workflow above runs a real backend in staging mode on a disposable
PostgreSQL database. It is not a claim about a Railway/Vercel deployment. Hosted
checks require a dedicated staging backend URL and test identities; do not direct
this harness at production. The browser preview must point to that staging backend,
not inherit the production API URL. Validate OAuth with two real GitHub sessions,
viewer/member permissions, production-style CORS and webhook delivery there.
The existing loopback checks cover the execution/evidence/report path without
requiring production accounts or targets.

Identity preflight fixtures also verify valid sessions before authorization traffic,
credential rejection, wrong principals, login HTML and redirects. Failed checks
send no authorization requests, preserve safe bound evidence, fail the job and
leave its assessment inconclusive. The request ceiling remains 100. See
[identity preflight](../../docs/identity-preflight.md) for authoring and rollout.

On Unix, pass the virtualenv's `bin/python` path. The launcher preserves that path
rather than following its symlink to the base Python, so installed Runner
packages remain available. Worker failures report redacted stderr and stop the
harness before a missing journal can mask the actual startup error.

## Semantic evidence and version compatibility

Add `--semantic-evidence` to require the coordinated Gate/Runner/Map evidence
path. This opt-in keeps the default baseline compatible with the older companion
commits pinned in CI. It adds three all-200 response-assertion cases (disclosure,
denial, unknown) and two masked-204 write cases with an independent reader,
principal preflights, per-identity reset and an owner positive control. The
complete run has 137 checks and a 140-request ceiling (133 actual requests).
It verifies raw HTTP separately from scanner conclusions, bound assertion
indices, value-free reader/reset/readback metadata, and unchanged confirmed
findings with all uploaded scan candidates still `new`.

Use `--map-ref`, `--runner-ref`, or `--gate-ref` to snapshot an exact local Git
revision instead of that checkout's working files. Refs must already exist
locally; the harness does not fetch them. Each run retains resolved commits,
file hashes, isolated database, worker artifacts and assertion results. Archive
paths/links are checked before extraction. Historical code is never rewritten.

The compatibility driver runs current sources and one older companion at a time:

```powershell
backend/venv/Scripts/python.exe scripts/integration/compatibility.py --runner ../VardrRunner --gate ../VardrGate --runner-python ../VardrRunner/venv/Scripts/python.exe --old-map bc4a7320edcc2b3e0907645aab6176740e659f01 --old-runner 5573f2c5e11600ccc817cc7de39240b3a4e36f00 --old-gate 612fa42fc88d2b9dff64c2500c56c0653cb014f9
```

An older combination is expected to fail the strict semantic contract while
passing all 104 baseline checks; a crash, incomplete run or baseline regression
never counts as expected incompatibility. `matrix.json` and each retained
`acceptance-results.json` identify the actual failed probes. This is a local
SQLite/loopback contract check, not browser, hosted OAuth or production validation.
Current sources include uncommitted changes and are identified by file hashes.

Deploy Map's semantic backend handling and the independent-verifier-capable
Runner before enabling Gate's new evidence path. An old Map may accept raw
uploads without retaining semantic conclusions. An old Runner may leave the
reader's `value_env` unresolved. An old Gate may run without the new strategy
and provenance behavior. Do not treat job completion or zero findings from these
mixed versions as proof of a clean authorization assessment. Re-run the strict
contract using the exact release candidates before rollout; do not infer support
from version strings or the baseline suite alone.
