# Development

## Prerequisites

- Python 3.12+
- Node.js 20 or 24 (CI tests both; 20 matches the Vercel / `.nvmrc` production runtime)
- PostgreSQL (or use Railway for a hosted instance)
- A GitHub OAuth App for local login

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
| `ENV` | No | Environment name. Set to `development` locally. Railway sets `RAILWAY_ENVIRONMENT_NAME` automatically. Controls whether HSTS is sent. |
| `MAX_UPLOAD_BYTES` | No | Max file size for tool imports in bytes. Default: `2097152` (2 MB). |
| `ANTHROPIC_API_KEY` | No | Anthropic API key. Required for `POST /programs/{id}/findings/{id}/suggest` (AI triage). If absent, the endpoint returns `503`. Obtain at [console.anthropic.com](https://console.anthropic.com). |
| `LOG_LEVEL` | No | Logging verbosity — `DEBUG`/`INFO`/`WARNING`/`ERROR`. Default: `INFO`. Logs are written to stdout (Railway captures stdout as the service log). An unrecognized value falls back to `INFO`. |
| `SENTRY_DSN` | No | If set, unhandled errors are reported to Sentry for aggregation and alerting. Unset disables Sentry (stdout logging still applies). `sentry-sdk` ships in `requirements.txt`; it is only imported when this is set. |
| `SENTRY_TRACES_SAMPLE_RATE` | No | Sentry performance-tracing sample rate, `0.0`–`1.0`. Default: `0.0` (error reporting only, no tracing). Only used when `SENTRY_DSN` is set. |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `AUTH_URL` | No | Full URL of this Next.js app. Auth.js v5 infers it from the incoming request, and uses `VERCEL_URL` on Vercel, so leave it unset unless you run behind a proxy that rewrites the host. (The v4 name was `NEXTAUTH_URL`; that variable is no longer read.) |
| `AUTH_SECRET` | Yes | Random secret for Auth.js session encryption. Generate with: `openssl rand -base64 32` |
| `AUTH_GITHUB_ID` | Yes | GitHub OAuth App client ID |
| `AUTH_GITHUB_SECRET` | Yes | GitHub OAuth App client secret |
| `BACKEND_JWT_SECRET` | Yes | Must match `BACKEND_JWT_SECRET` in `backend/.env` exactly |
| `NEXT_PUBLIC_API_URL` | Yes | Backend base URL. Local: `http://localhost:8000`. Production: your Railway backend URL. |

### Setting up a GitHub OAuth App

1. Go to GitHub → Settings → Developer settings → OAuth Apps → New OAuth App
2. Set **Authorization callback URL** to `http://localhost:3000/api/auth/callback/github` (local) or your Vercel URL in production
3. Copy the **Client ID** and **Client Secret** into the frontend `.env.local`

---

## Running Tests

Tests use SQLite (in-memory via `test_vardrmap.db`), not PostgreSQL. The test database is rebuilt from scratch on each run — `conftest.py` calls `drop_all()` then `create_all()` to ensure the current schema is always used.

```bash
cd backend

# Windows (venv inside backend/)
.\venv\Scripts\pytest.exe tests -v

# macOS / Linux
pytest tests -v
```

All 329 tests should pass.

The frontend has its own Jest suite — run it with `cd frontend && npm test`. It
covers the global reducer (`app/context/__tests__/`) and React components
(`app/components/__tests__/`, rendered with React Testing Library under a jsdom
environment).

### Test coverage areas

| File | What it tests |
|---|---|
| `tests/test_programs.py` | Program CRUD, ownership isolation (BOLA) |
| `tests/test_findings.py` | Finding CRUD, cross-program access denial |
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
  → 0014clientsauthorizations → 0015dropsubmissions (head)
```

### Production (Railway)

Railway runs `bash start.sh` on every deploy. That script waits for Postgres to accept queries (`python wait_for_db.py`), then runs `alembic upgrade head`, then starts uvicorn — so migrations are applied automatically on each deploy. `create_all` does not run in production — Alembic is the only schema authority.

The readiness wait is not optional. Railway starts the app container and the database concurrently, and a database still in recovery returns `FATAL: the database system is starting up`. Without the gate, alembic fails, `set -e` kills the container, and the three retries allowed by `railway.json` are spent before the database finishes starting.

### Local development

`main.py` calls `Base.metadata.create_all()` when `ENV=development` (the default locally). This keeps the local dev loop fast — you don't need to run migrations just to start the server. When you add a new model or column, generate a migration so production can receive it:

```bash
alembic revision --autogenerate -m "short description"
```

Review the generated file in `migrations/versions/` before applying — autogenerate can miss some changes (e.g. column type changes, custom constraints).

**Apply pending migrations locally:**
```bash
alembic upgrade head
```

**Stamp an existing database without running migrations** (use this when setting up Alembic on a database that already has the schema):
```bash
alembic stamp head
```

**Check current revision:**
```bash
alembic current
```

### Test database

Tests use SQLite and rebuild the schema from scratch on every run via `drop_all() + create_all()` in `conftest.py`. Alembic migrations do not run in tests — the SQLite schema always reflects the current model definitions.

---

## VardrRunner Setup

VardrRunner is the local CLI that runs tools on your machine and uploads results to
VardrMap. **It now lives in its own repository:
[jorge-aquino/VardrRunner](https://github.com/jorge-aquino/VardrRunner).** Install, CLI,
daemon, and tool-prerequisite instructions are documented there — see its
[README](https://github.com/jorge-aquino/VardrRunner#readme) and
[docs/](https://github.com/jorge-aquino/VardrRunner/tree/main/docs).

> **Naming:** the CLI command is `vardrrunner`. API keys use the `vmap_` prefix — these are different things.

To connect a runner to this VardrMap instance:

1. Create a `vmap_` API key in **Settings → API Keys** (use a `runner`-scoped key for a VPS).
2. On the runner, run `vardrrunner login vardrmap` and enter your VardrMap URL + the key.
   Config is saved to `~/.vardrmap/config.json` (plaintext key — restrict with
   `chmod 600` on Unix).
3. Run `vardrrunner heartbeat`. The Bridge in the Jobs section shows the runner online
   (green) for 5 minutes after the last heartbeat.

The runner polls `GET /jobs/pending`, claims jobs atomically, executes tools locally
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
