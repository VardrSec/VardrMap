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

On Unix, pass the virtualenv's `bin/python` path. The launcher preserves that path
rather than following its symlink to the base Python, so installed Runner
packages remain available. Worker failures report redacted stderr and stop the
harness before a missing journal can mask the actual startup error.
