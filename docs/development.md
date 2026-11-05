# Development

## Explicit managed service configuration

This development candidate exposes managed factories only when
`VARDRMAP_MANAGED_WORKER=1`. Omission or `0` preserves default startup. Other flag
values and incomplete enabled configuration refuse startup with a fixed error.
Apply additive schema `0039managedruntime` through the existing migration procedure;
configuration never applies migrations or repairs state.

Supply these values explicitly in the API's reviewed worker-enabled profile:

| Variable | Required value |
| --- | --- |
| `VARDRMAP_MANAGED_ORIGIN` | Exact configured HTTPS issuer URL including API prefix; must match enrollment and Runner configuration. |
| `VARDRMAP_MANAGED_ISSUER_ID` | Existing trusted issuer identifier. |
| `VARDRMAP_MANAGED_CONTRACT_KEY_ID` | Distinct contract-signing key identifier. |
| `VARDRMAP_MANAGED_CONTRACT_KEY_FILE` | Absolute path to an existing regular raw 32-byte Map contract key, supplied only to the API. |
| `VARDRMAP_MANAGED_OPERATOR_TRUST_FILE` | Absolute path to existing public operator anchor JSON, capped at 32 KiB. |

The public anchor file is a list of 1–100 exact objects containing `issuer_id`,
`key_id`, `approver_id`, unpadded base64url `public_key`, and boolean `revoked`.
`approver_id` names the existing owner. Existing `ContractWire` checks distinct
approval/contract keys, duplicate anchors and signature purpose. Private operator
approval keys remain outside Map and the worker. This loader generates no key,
creates no user/enrollment/approval and runs no database operation or target work.
Keep private key custody and mounts scoped to the API; do not put raw keys in
arguments, public trust, Runner state or logs. Ordinary startup stays disabled.

Configuration checks use disposable keys without database access. Actual managed
worker, stop, disconnected/restart and recovery acceptance remains required before
calling the configured distribution supported. Historical ADRs describing
unregistered prototypes retain their original scope; this opt-in supplies the
explicit assembly seam.

`tests/test_managed_stops.py` exercises both result/stop receipt orderings with
active, expired and approval-revoked permission, including retained evidence,
immutable replay, capacity release and conservative spent allowances.

## Explicit managed key binding

An installation operator can invoke `python -m managed_enrollment` from the
configured backend environment after the existing managed schema is installed.
The command uses that environment's existing database credential; it creates no
account, API key, signing key, authority or approval. Development checks use only
disposable databases and synthetic keys.

Select the existing owner ID from the authenticated `/me` response, an existing
API-key ID from `/auth/apikeys`, and the intended installation's stable UUID from
`vardrrunner identity show`. The API key must already belong to that owner with
runner or full scope. The origin must exactly match the trusted Map issuer URL.
Replace the non-secret placeholders below:

```text
python -m managed_enrollment bind --owner OWNER_ID --api-key-id KEY_ID --runner-id RUNNER_UUID --origin https://vardrsec.localhost:8443/backend
python -m managed_enrollment revoke --owner OWNER_ID --enrollment-id ENROLLMENT_ID
```

Binding prompts for the existing key through hidden TTY input. Without a TTY it
refuses unless automation explicitly selects `--key-stdin`; that mode reads at
most 259 bytes and accepts one ASCII key of at most 256 bytes plus optional LF or
CRLF. The input pipe must close after that key. The raw key is never printed,
written or accepted as an argument; no environment or plaintext-file fallback is
added. Successful output contains association metadata only. Revocation needs no
recovered key and retains its tombstone/revision. Repeating an exact active bind
or revocation is idempotent. Rebinding a revoked association, changing bound
metadata, revision overflow and missing schema are refused without repair or
migration. A unique-constraint
race refuses safely; a later exact invocation can observe its retained winner.

Binding is separate from approval and creates no execution permission. An owner
session must obtain an unsigned context through the unregistered approval factory,
the operator signs it outside Map using existing separately provisioned signing
material, and the owner registers that exact receipt. Existing public operator
trust and Map's distinct contract-signing key must already be configured in the
injected issuer. No private approval key is sent to Map or the worker. The HTTP
factories remain absent by default; explicit service configuration and worker
activation are separately controlled.

Managed issuance checks use `tests/test_managed_issuance.py` and
`postgres_tests/test_managed_issuance.py`. Keep synthetic association/key records,
independent signing purposes, real administrator/restricted-role lock races,
denied-clock interleavings, post-lock expiry and stale ORM identities in coverage.
Inspect exact rollback of all fees, ownership, ordinals and case snapshots. The
PostgreSQL fixture must use a disposable `vardrmap_test*` database; local native
validation uses verify-full TLS/SCRAM with its own temporary CA. Never disable TLS
or use host firewall/service changes for these tests. Raw failures stay private;
review metadata is explicitly sanitized. No actual tool is invoked in this slice.

`backend/tests/test_managed_wire.py` verifies public synthetic v1 wire vectors,
purpose/key separation, owner provenance, expiry and bounded parsing. Run tests
with an explicit child-process environment allowlist, synthetic authentication,
disposable `vardrmap_test*` database and `PYTHON_DOTENV_DISABLED=1`. Installed
python-dotenv 1.2.4 supports this before file discovery; never read retained `.env`
or install into retained test environments. Raw failure output stays private;
review evidence uses explicitly labeled sanitized derivatives. The adapter is
unregistered and does not import Runner code. See [wire boundary](adr/0006-managed-contract-wire.md).

NM-2 cancellation uses disposable fixtures in `backend/tests/test_execution_control.py`.
Run `backend/postgres_tests/test_execution_control.py` against a dedicated
`vardrmap_test*` PostgreSQL database to verify real cancellation/finalization lock
ordering as both administrator and application role. SQLite does not verify those
locks. Migration `0032executioncontrol` is additive; do not apply it to retained
installations for development checks. Its downgrade retains fences by refusing
table deletion. Whole NM-2 acceptance is separate from this first increment.

## Prerequisites

For local-account development, install the updated backend requirements and read
the [local authentication guide](local-authentication.md). Both browser UI and API
must use HTTPS with trusted certificates and explicit allowed origins. Default
GitHub-only development is unchanged. Account bootstrap/recovery are explicit
terminal commands and never run during application startup. The additional
HTTPS browser acceptance profile uses a disposable self-signed fixture certificate
and no real user credentials; its TLS exception is limited to that test context.

- Python 3.12+
- Node.js 20 or 24 (CI tests both; 20 matches the Vercel / `.nvmrc` production runtime)
- PostgreSQL (or use Railway for a hosted instance)
- A GitHub OAuth App only when the `github` login method is enabled

For the isolated three-product API engagement test, see
[`scripts/integration/README.md`](../scripts/integration/README.md). It uses real
Runner and Gate execution with a loopback fixture and disposable SQLite or
PostgreSQL database.

---

## Backend Setup

```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in all values (see [Environment Variables](#environment-variables) below).

Start the dev server:
```bash
uvicorn main:app --reload
```

The API is now at `http://localhost:8000`. FastAPI's auto-generated docs are at `http://localhost:8000/docs`.

---

## Frontend Setup

```bash
cd frontend
npm install
cp .env.example .env.local
```

Edit `.env.local` and fill in all values.

Start the dev server:
```bash
npm run dev
```

The app is now at `http://localhost:3000`.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string. For Railway, this is provided automatically. Local example: `postgresql://user:password@localhost:5432/vardrmap` |
| `BACKEND_JWT_SECRET` | Yes | Random secret shared with the frontend for JWT signing. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`. Must match the frontend value exactly. |
| `ALLOWED_ORIGINS` | Yes | Comma-separated list of allowed CORS origins. Local: `http://localhost:3000` |
| `ENV` | No | Environment name. Set to `development` locally. Railway sets `RAILWAY_ENVIRONMENT_NAME` automatically. HSTS is sent only when this resolves to exactly `production` — any other value, including a typo, fails to the safe side and sends no HSTS. |
| `MAX_UPLOAD_BYTES` | No | Max file size for tool imports in bytes. Default: `2097152` (2 MB). |
| `ANTHROPIC_API_KEY` | No | Anthropic API key for finding suggestions and scanner triage (`POST /engagements/{id}/findings/{id}/suggest` and `POST /engagements/{id}/scans/triage`). Nonempty requests without a key return `503`; empty triage returns an empty list. Inputs are heuristically redacted; do not send restricted client evidence to the provider. Obtain at [console.anthropic.com](https://console.anthropic.com). |
| `LOG_LEVEL` | No | Logging verbosity — `DEBUG`/`INFO`/`WARNING`/`ERROR`. Default: `INFO`. Logs are written to stdout (Railway captures stdout as the service log). An unrecognized value falls back to `INFO`. |
| `SENTRY_DSN` | No | If set, unhandled errors are reported to Sentry for aggregation and alerting. Unset disables Sentry (stdout logging still applies). `sentry-sdk` ships in `requirements.txt`; it is only imported when this is set. |
| `SENTRY_TRACES_SAMPLE_RATE` | No | Sentry performance-tracing sample rate, `0.0`–`1.0`. Default: `0.0` (error reporting only, no tracing). Only used when `SENTRY_DSN` is set. |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `AUTH_URL` | No | Full URL of this Next.js app. Auth.js v5 infers it from the incoming request, and uses `VERCEL_URL` on Vercel, so leave it unset unless you run behind a proxy that rewrites the host. (The v4 name was `NEXTAUTH_URL`; that variable is no longer read.) |
| `AUTH_SECRET` | Yes | Random secret for Auth.js session encryption. Generate with: `openssl rand -base64 32` |
| `VARDRMAP_AUTH_METHODS` | No | `github` (default), `local`, or `github,local`; set consistently on backend and frontend |
| `AUTH_GITHUB_ID` | When GitHub enabled | GitHub OAuth App client ID |
| `AUTH_GITHUB_SECRET` | When GitHub enabled | GitHub OAuth App client secret |
| `BACKEND_JWT_SECRET` | Yes | Must match `BACKEND_JWT_SECRET` in `backend/.env` exactly |
| `NEXT_PUBLIC_API_URL` | Yes | Backend base URL. Default GitHub-only development: `http://localhost:8000`. Local-account browsers require trusted HTTPS for both API and UI; see the local-authentication guide. |

### Setting up a GitHub OAuth App

This section applies only when `github` is enabled in `VARDRMAP_AUTH_METHODS`.

1. Go to GitHub → Settings → Developer settings → OAuth Apps → New OAuth App
2. Set **Authorization callback URL** to `http://localhost:3000/api/auth/callback/github` (local) or your Vercel URL in production
3. Copy the **Client ID** and **Client Secret** into the frontend `.env.local`

---

## Running Tests

Tests default to file-backed SQLite (`test_vardrmap.db`). Set `TEST_DATABASE_URL`
to run them against a disposable PostgreSQL database named `vardrmap_test*`.
The backend suite drops and recreates its tables on each run; never point it at
valuable data. Test users go through `/auth/sync` before creating owned resources.

```bash
cd backend

# Windows (venv inside backend/)
.\venv\Scripts\pytest.exe tests -v

# macOS / Linux
pytest tests -v
```

All 700+ tests should pass.

The frontend has its own Jest suite — run it with `cd frontend && npm test`. It
covers the global reducer (`app/context/__tests__/`) and React components
(`app/components/__tests__/`, rendered with React Testing Library under a jsdom
environment).

`npm run typecheck` (`tsc --noEmit`) is the only thing that type-checks test files:
`next build` reaches only what the app graph imports, and ts-jest transpiles without
checking. CI runs it inside the required **Frontend lint + build** job. The
`renderWithApp` harness in `frontend/test-utils/` casts through
`as unknown as AppContextValue`, which defeats excess-property checking, so removing
something from `AppContext` will not fail typecheck there — grep `frontend/test-utils/`
by hand.

### Test coverage areas

| File | What it tests |
|---|---|
| `tests/test_engagements.py` | Engagement CRUD, ownership isolation (BOLA), type/status/date fields |
| `tests/test_findings.py` | Finding CRUD, cross-engagement access denial |
| `tests/test_security_headers.py` | Security headers on normal, error, auth-failure and CORS preflight responses; HSTS is production-only |
| `tests/test_report_lifecycle.py` | Deliverable statuses accepted, retired bounty statuses rejected, migration mapping |
| `tests/test_engagement_list_queries.py` | `GET /engagements` query count does not grow per engagement |
| `tests/test_imports.py` | File upload parsing, extension/size validation, BOLA |
| `tests/test_jobs.py` | Scan job CRUD, BOLA isolation, status transitions |
| `tests/test_job_events.py` | Job event creation, ordering, cascade delete, BOLA isolation |
| `tests/test_runner_heartbeat.py` | Runner heartbeat upsert, status derivation (online/offline), BOLA isolation |
| `tests/test_apikeys.py` | Key generation, API key auth at `/me`, revocation, BOLA isolation, max-key limit |
| `tests/test_auth.py` | JWT validation — missing, expired, wrong audience, garbage token |
| `tests/test_sanitization.py` | XSS/injection rejection and stripping across input fields |
| `tests/test_members.py` | Program member CRUD, BOLA isolation, ownership guards |

---

## Database Migrations

Migrations use Alembic. The migration chain is:

```
0001baseline → 0002addcreatedat → 0003addapikeys → 0004addscanjobs → 0005runnerheartbeats
  → 0006addjobeevents → 0007servicesapikey → 0008radarservice → 0009submissions
  → 0010schednotify → 0011rbacreconscopes → 0012programidindexes → 0013pipelineprofiles
  → 0014clientsauthorizations → 0015dropsubmissions → 0016policyengine → 0017organizations
  → 0018assetgraph → 0019evidence → 0020assetfks → 0021authztestcases
  → 0022reportlifecycle (head)
```

Confirm the chain has not forked before committing a new revision — two
revisions naming the same `down_revision` make `alembic upgrade head` fail, and
Railway will not come up:

```bash
.\venv\Scripts\python.exe -m alembic heads   # must print exactly one line
```

### Production (Railway)

Railway runs `bash start.sh` on every deploy. That script waits for Postgres to accept queries (`python wait_for_db.py`), then runs `alembic upgrade head`, then starts uvicorn — so migrations are applied automatically on each deploy. `create_all` does not run in production — Alembic is the only schema authority.

The readiness wait is not optional. Railway starts the app container and the database concurrently, and a database still in recovery returns `FATAL: the database system is starting up`. Without the gate, alembic fails, `set -e` kills the container, and the three retries allowed by `railway.json` are spent before the database finishes starting.

### Local development

`GET /health` continues to report API liveness. The separate `GET /ready` returns
200 only with a reachable database and the current Alembic marker; a create-all
development/test database without migration history intentionally returns 503.
Do not use `alembic stamp` to hide drift. Use the existing migration procedure on
a disposable development database; restore from a verified backup when recovering
real data. Readiness probes never run migrations. The PostgreSQL migration suite
also checks readiness after a real upgrade and confirms that an older schema
remains unchanged after an unready probe.

`main.py` calls `Base.metadata.create_all()` when `ENV=development` (the default locally). This keeps the local dev loop fast — you don't need to run migrations just to start the server. When you add a new model or column, generate a migration so production can receive it:

```bash
alembic revision --autogenerate -m "short description"
```

Review the generated file in `migrations/versions/` before applying — autogenerate can miss some changes (e.g. column type changes, custom constraints).

**Apply pending migrations locally:**
```bash
alembic upgrade head
```

**Fresh database:** run `alembic upgrade head`. The baseline creates the frozen
historical schema and subsequent revisions bring it current. No `create_all` or
manual stamping is needed. Repeated upgrades are safe.

**Existing unstamped database:** inspect its schema and identify its actual
revision before stamping. For example, only a database matching the pre-Alembic
baseline should use:
```bash
alembic stamp 0001baseline
alembic upgrade head
```
Do not stamp `head` to bypass missing tables or migrations. Nonempty unstamped
databases are refused by the baseline. Its downgrade retains historical tables.

**Check current revision:**
```bash
alembic current
```

### Test database

The backend suite rebuilds the current ORM schema. The separate PostgreSQL
migration tests instead create disposable schemas, run Alembic from empty and
historical baselines, verify retained data, and start the app without `create_all`.
Each of these tests runs twice: once with the database administrator in
`TEST_DATABASE_URL`, and once with a temporary login role that has no SUPERUSER, CREATEDB,
CREATEROLE, REPLICATION or BYPASSRLS and owns only its test schema. The distribution runs
the API and migrations as such a role, so migrations must not need superuser features.

From `backend/`, with an existing disposable PostgreSQL database:

```powershell
$env:TEST_DATABASE_URL = 'postgresql://user:password@127.0.0.1:5432/vardrmap_test_local'
.\venv\Scripts\python.exe -m pytest postgres_tests -v
.\venv\Scripts\python.exe -m pytest tests -v
```

Application and migration connections enforce UTC regardless of the server's
default timezone. TLS remains required by default; an explicit `sslmode` URL
parameter is honored (for example `?sslmode=disable` on a disposable local/CI
instance without TLS). No existing timestamp values are rewritten.

CI sets its database default to `America/Chicago`, runs these checks and the
backend suite, then executes the [three-product acceptance check](../scripts/integration/README.md)
against a second empty PostgreSQL database.

---

## VardrRunner Setup

VardrRunner is the local CLI that runs tools on your machine and uploads results to
VardrMap. Install the published package in an isolated environment:

```bash
pipx install vardrrunner
```

Update it with `vardrrunner update` (VardrRunner 0.50.0 or later), which runs
`pipx upgrade vardrrunner` and confirms the new version; `vardrrunner doctor` says when an
update exists. A copy on 0.49.0 or older needs one `pipx upgrade vardrrunner` first. For uv or
a plain virtualenv install, `vardrrunner update` prints that installer's command instead.

`pip install vardrrunner` is also supported. For a one-shot command without a
persistent installation, use `uvx vardrrunner <command>`. The source lives in
[VardrSec/VardrRunner](https://github.com/VardrSec/VardrRunner). CLI,
source-development, and tool-prerequisite instructions are documented there — see its
[README](https://github.com/VardrSec/VardrRunner#readme) and
[docs/](https://github.com/VardrSec/VardrRunner/tree/main/docs).

> **Naming:** the CLI command is `vardrrunner`. API keys use the `vmap_` prefix — these are different things.

To connect a runner to this VardrMap instance after installation (the same steps
**Settings → Connect Runner** shows in the app, each with a Copy button):

1. **Get a runner key.** In **Settings → Connect Runner**, click **Generate Runner Key** and
   copy the `vmap_` key. It is shown once and is runner-scoped (jobs, imports and heartbeat only).
2. **Connect the machine.**

   ```bash
   vardrrunner init --url <your VardrMap API URL> --no-install-tools
   ```

   Paste the key at the hidden prompt. `init` stores it in the OS keychain (it refuses to
   write a plaintext key unless you pass `--allow-plaintext-credentials`), sets the runner
   name and finishes with `doctor`. It is safe to rerun. Avoid `--key` on the command line:
   it puts the key in shell history. VardrRunner runs only when invoked and installs no
   startup service. (0.47.0 still asks whether to install a background service; answer no.
   A service installed by 0.47.0 or earlier is removed by hand; see VardrRunner's
   [upgrade notes](https://github.com/VardrSec/VardrRunner/blob/main/docs/cli.md#upgrading-from-0470-or-earlier).)
3. **Install or check the tools.**

   ```bash
   vardrrunner tools install --all
   ```

   Safe to rerun: it installs missing tools, updates outdated ones, repairs missing or
   changed binaries, skips verified ones, and reports whether nmap and vardrgate (which it
   cannot install) are on `PATH`. VardrGate is only needed for `vardrgate_api_test` jobs.
   **Settings → Connect Runner** step 5 has a copyable install command for Windows
   (PowerShell) and for macOS/Linux: each downloads the pinned VardrGate release
   (`VARDRGATE_VERSION` in `frontend/app/lib/vardrgateInstall.ts`), checks it against that
   release's `SHA256SUMS`, refuses it on a mismatch, and puts it on `PATH`
   (`%LOCALAPPDATA%\Programs\VardrGate` or `~/.local/bin`). Bump the pin when VardrGate
   releases. Or get it from the
   [VardrGate releases](https://github.com/VardrSec/VardrGate/releases/latest) and check it
   against `SHA256SUMS` by hand. Keep it out of `~/.vardrmap/tools`: VardrRunner refuses any
   binary there that it did not install. The per-tool report needs VardrRunner 0.48.0 or later;
   0.47.0 installs the same way with less detail.
4. **Check the connection.** Run `vardrrunner heartbeat`, then click **Verify connection** in
   Settings. The runner shows online for 5 minutes after its last heartbeat (`jobs run` also
   sends one). If it does not, run `vardrrunner doctor`.
5. **Start on an engagement.** `vardrrunner engagements` lists IDs, `vardrrunner scope <id>`
   shows what is in scope, and `vardrrunner run httpx --engagement <id> --scope` checks which
   in-scope hosts are live. After that, queue scans from the Jobs tab. Queued jobs wait on the
   backend until you run `vardrrunner jobs run` on the runner machine; nothing executes them
   in the background.

On a headless server with no keychain, set `VARDRMAP_API_KEY` instead, and see the
VardrRunner [CLI reference](https://github.com/VardrSec/VardrRunner/blob/main/docs/cli.md)
for `init --production`. A runner set up with the
old `vardrrunner login` flow may still hold a plaintext key in `~/.vardrmap/config.json`;
`vardrrunner credentials` shows where the key is read from.

`vardrrunner jobs run` fetches `GET /jobs/pending` once, claims jobs atomically, executes tools locally
(scan traffic always originates from your machine, never Railway), and posts results and
lifecycle events back over HTTP. See [architecture.md](architecture.md#job-queue-flow) for
the full integration contract.

---

## Adding a New Feature

When adding a router, model change, or notable behavior change, update these files:

1. `backend/models.py` — add or modify models
2. `backend/schemas.py` — add Pydantic request/response schemas with validation
3. `backend/routers/<resource>.py` — add routes with `get_current_user` and `log_action`
4. `backend/main.py` — include the new router
5. `backend/migrations/versions/` — create a migration if the schema changed
6. `frontend/app/types.ts` — add or update TypeScript types
7. `frontend/app/components/` — add or update the relevant section component
8. `docs/api.md` — document the new endpoints
9. `CHANGELOG.md` — add an entry under the current version

---

## Linting and Build

```bash
# Frontend lint
cd frontend && npm run lint

# Frontend production build (catches TypeScript errors)
cd frontend && npm run build
```

Both should pass clean before committing. The project uses `eslint-config-next` — the rules that matter most are `no-explicit-any` and `react-hooks/exhaustive-deps`.
## Burp Suite extension

The optional Java 21 Montoya extension lives in `integrations/vardr-burp` and is
independent of VardrRunner. Build it with `gradle jar`, load the resulting JAR
as a Java extension in Burp, then configure the VardrMap backend URL,
engagement ID, and a full-scope personal API key in its suite tab. The key is
held in memory only. Use the request context menu to promote selected traffic;
automatic capture is intentionally unavailable. Select the originating Burp
tool in the suite tab so API Surface provenance is useful; multi-selected
messages are promoted individually.

## Dependency hygiene

Install from the repository requirements and lockfile before interpreting test
results; an old virtual environment can differ from the deployed versions.
Run `python -m pip check`, audit the installed Python dependency closure and run
`npm audit` after updating dependencies. urllib3 is explicitly pinned because it
is Sentry's transitive HTTP transport. Use compatible updates and rerun frontend
lint, typecheck, tests and build; do not blindly apply `npm audit fix --force`.
See [the code audit](code-audit-2026-10-11.md) for remaining development-tool advisories.

## Browser acceptance

From `frontend`, install the locked packages with `npm ci`, install Chromium with
`npx playwright install chromium`, then run `npm run test:e2e`. Linux CI uses
`npx playwright install --with-deps chromium`. Set `E2E_PYTHON` to a backend Python
interpreter if it is not `../backend/venv/Scripts/python.exe` on Windows or
`python` on Unix. It needs the backend requirements installed.

The suite owns ports 3006 and 8765 and refuses to reuse an existing server. It
starts Next in development mode and a real loopback FastAPI backend with a fresh
temporary SQLite database and fixture signing key. The backend ignores any
inherited database URL and removes the AI provider key. All application API calls
are real; only `/api/auth/session` is intercepted in the test browser with fixture
identities. No test-login provider or auth bypass is added to the application.
Real GitHub OAuth and deployed configuration still need hosted staging checks.

Run `npm run test:e2e:local` for the separate local-authentication browser journey.
It owns HTTPS loopback ports 3007/8766, bootstraps a disposable SQLite account,
and exercises real login, authorized engagement creation, missing-CSRF rejection,
password rotation, session replay rejection and logout without session stubs.
OpenSSL must be available (`openssl` on PATH, or Git for Windows' bundled binary).
The fixture generates one-day certificates under ignored `.local-auth-e2e/` and
does not install trust or change global TLS settings. Only this Playwright profile
accepts its self-signed certificates. Both auth methods are configured; the suite
checks GitHub remains offered, but does not contact GitHub or replace OAuth
staging checks. Use one browser suite at a time because both own the Next dev
output directory. No production database or credentials are used.

The mixed-session extension intercepts only GitHub session metadata with a signed
fixture identity; the local cookie, backend authorization and API calls remain
real. It checks provider failure/expiry, explicit local selection with an existing
GitHub identity, reload and sign-out. This is distinct from a real OAuth callback
or the [trusted fresh-install HTTPS acceptance](local-https-acceptance.md).

Four browser journeys cover login presentation, pentest/client creation, job
preview/queueing, synthetic candidate import/promotion, immutable report creation
and Markdown download, viewer access/revocation, and expired backend identities.
Browser queueing does not execute a scanner; the separate
[integration harness](../scripts/integration/README.md) runs the actual Runner
and Gate. Never point these fixtures at production. Playwright traces/screenshots
and reports are ignored by Git; CI retains failed browser artifacts for seven days.

## API assessment/playbook compatibility

Identity preflight additionally needs the matching Gate/Runner pair. Deploy Map
before using these cases, upgrade both executors, and run the expanded disposable
acceptance harness. New Runner refuses older Gate binaries through a required CLI
flag; older Runner versions lack that guard. No new environment variable or hosted
test account is needed. See [identity preflight](identity-preflight.md).

Apply the additive 0027 migration before deploying this frontend or serving new
Runner playbook tools. Use Runner's matching result-binding release for assessments:
older runners can upload evidence, but their missing case hash stays inconclusive.
No new environment variables or dependency packages are required. Downgrading 0027
removes its new assessment/provenance columns (losing that metadata) while retaining
existing job/case/evidence rows; export before a deliberate rollback.

Backend regression tests cover unknown/partial decisions and case edit races.
PostgreSQL checks include upgrade/downgrade and SET NULL retention. Browser
acceptance exercises playbook guidance, partial assessments and evidence linking;
the loopback three-repository harness exercises actual Gate execution.

## Container development

The explicit `backend/tests/test_managed_entry.py` fixture additionally requires
`NM2_PRECLAIM_ENTRY=1` and the existing native/TLS opt-ins. It exercises Runner's
unregistered one-shot entry using a test-only claim adapter that includes the
actual frozen case snapshot. It verifies local evidence retention, ambiguous
claim/binding holds and local stop without uploads, completion or release.
See [ADR 0007](adr/0007-transactional-managed-issuance.md). Use only disposable
profiles/databases, synthetic trust and owned loopback resources.

See [container setup](containers.md) for build contexts, non-root runtime, build-time API URL and proxy trust. These images retain the existing hosted authentication configuration.

Settings includes [platform/Runner observations](platform-status.md) without new
configuration or a migration. Update the backend before the frontend for the
additive heartbeat metadata. The local HTTPS browser journey checks real unready
SQLite readiness, a real account-owned heartbeat, and an injected readiness
transport failure. Frontend tests cover stale, unknown, malformed and failed polls.
These fixtures do not certify fresh-host certificate trust or a full diagnostic run.

## Local NM-2 consumption fixtures

`tests/test_managed_consumption.py` checks exact acknowledgements, changed bindings,
revocation/expiry, delayed rollback and independent-connection winner selection.
With explicit `NM2_RUNNER_SOURCE`, `tests/test_managed_http.py` also sends actual
API-key-authenticated JSON through the test-only ASGI adapter to the production
Runner ACK parser, including a lost post-commit reply. No target is dispatched.

`postgres_tests/test_managed_issuance.py` repeats single-use, race and delayed-write
checks in migrated schemas as administrator and the restricted application role.
Use a disposable `vardrmap_test*` database with explicit certificate trust and TLS
verification. The Windows/TLS entry adapter has been updated but still requires
real Windows execution; portable fixtures do not accept native containment.

With `NM2_TLS_LOOPBACK=1` and the matching Runner source, the real socket suite
also verifies the consumption ACK and a truncated post-commit response through
Runner's existing `api.py` client. It keeps explicit CA/hostname verification,
zero retries and zero redirects on fixture instances. This is loopback transport
evidence, not real Windows containment or an activated production adapter.

## Managed evidence/completion verification

`tests/test_managed_results.py` checks case/contract binding, redaction, immutable
replay, preflight failure, permission denial, delayed rollback and competing
result/outcome transactions. Legacy Gate/semantic tests continue to use the same
projection. PostgreSQL scenarios repeat migrations, evidence and completion races
and rollback as administrator and restricted application role, with verified TLS.

With matching `NM2_RUNNER_SOURCE`, ASGI fixtures exercise the real Runner receipt
parser. `NM2_TLS_LOOPBACK=1` additionally checks real sockets and truncated replies
after actual result or terminal commit; no target is dispatched. The separate
Windows/TLS native entry finalization test remains deferred to Papachin and is
not certified by cloud passes. See [ADR 0009](adr/0009-managed-result-receipts.md).

## Managed known-stop verification

`tests/test_managed_stops.py` covers exact reporting, unknown/foreign denials,
receipt immutability, competing reports, write rollback and tombstone retention
after job deletion. Authenticated ASGI/verified loopback TLS fixtures exercise
the real Runner receipt parser, including loss after actual server commit.
PostgreSQL repeats known-stop/race/rollback/retention cases under both database
roles against the migrated 0038 head. Real Windows native reporting is explicitly
opt-in and remains a separate Papachin gate; cloud fixtures cannot accept it.
See [ADR 0010](adr/0010-managed-known-stop-receipts.md).

## Managed claim observation fixtures

The claim observation tests cover lost claim replies, expired/revoked approvals,
wrong enrolled keys, inconsistent state, races, source changes and receipt
regressions. Runner restart fixtures require prior durable native result/stop
proof; generic terminal metadata cannot close a run. Map's fixture-only HTTP and
verified TLS adapters exercise the production Runner parser. PostgreSQL repeats
absence, claim races and terminal receipts under both database roles. Full-suite
coverage/static checks remain required. Windows/Papachin, independent acceptance,
CI/security and migration gates remain open. No production route is registered.

## Explicit Runner managed transport fixtures

The browser acceptance suite also checks visible session expiry. Provider-level
401 handling retains its specific notice across concurrent bootstrap requests;
ordinary engagement errors and success toasts keep their existing behavior.
`AppContext.test.tsx` covers concurrent bootstrap responses and the ordinary toast timer.

The opt-in verified TLS suite exercises Runner's bounded managed JSON primitive
with actual authentication, result/stop/observation flows, redirects, invalid CA,
ambiguous claim replies and size/JSON negatives. Test adapters alone register
fixture routes; no production Map route, key, enrollment or migration is added.
See [canonical NM-2 exit status](nm2-canonical-exit-status.md): this does not prove
the required operator-enabled Docker Desktop worker or Linux/container control.

## Read-only managed observation adapter tests

`tests/test_managed_observation_http.py` mounts only the explicit router factory
in a synthetic app, with actual API-key authentication and disposable SQL. It
checks unchanged business state and authorization failures, exact bounded inputs,
read timeout/disconnect, no capability/error reflection and absence from `main`.
The opt-in TLS suite sends result and stop observations through this adapter using
the unchanged Runner managed transport. No production route or key is provisioned.
See [ADR 0012](adr/0012-unregistered-observation-http.md). Worker/container and
independent acceptance gates remain open.

## NM-2 remaining verification and decisions

The observation HTTP PostgreSQL cases use migrated administrator/restricted roles
and actual API authentication/request-scoped sessions through the threadpool.
Verified TLS additionally emulates existing Full `/backend` prefix stripping while
preserving the exact signed API-base identity and result/stop receipts. Neither
fixture enrolls live credentials or executes a target. The
[pending worker decision record](nm2-worker-decisions-pending.md) lists approved
constraints and unresolved containment/bootstrap/lifecycle choices; none is chosen.

Run PostgreSQL test collection from `backend`: `python -m pytest postgres_tests -v`.
These modules share fixtures through the `postgres_tests` package; invoking that
directory from the repository root does not establish its parent import path.

PostgreSQL CI enables direct Runner HTTP/TLS probes in the Map test interpreter.
Install the pinned companion with its authorization extra in that interpreter;
the separate CLI virtual environment alone does not satisfy those imports. This
is a CI fixture dependency, not a Map application/runtime requirement.
