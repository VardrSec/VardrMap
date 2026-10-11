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

This is an opt-in integration check. It does not exercise the browser UI or
PostgreSQL behavior, and should supplement the repositories' normal test suites.
