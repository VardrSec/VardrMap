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
| `NEXTAUTH_URL` | Yes | Full URL of this Next.js app. Local: `http://localhost:3000`. On Vercel this is set automatically. |
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
0001_baseline → 0002_add_created_at → 0003_add_api_keys → 0004_add_scan_jobs → 0005_add_runner_heartbeats → 0006_add_job_events → 0007_add_services → 0008_add_radar → 0009_submissions → 0010schednotify → 0011rbacreconscopes
```

### Production (Railway)

Railway runs `bash start.sh` on every deploy. That script runs `alembic upgrade head` before starting uvicorn, so migrations are applied automatically on each deploy. `create_all` does not run in production — Alembic is the only schema authority.

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

VardrRunner is the local CLI that runs tools on your machine and uploads results to VardrMap. It lives in `runner/` and is installed separately from the backend.

> **Naming:** the CLI command is `vardrrunner`. API keys use the `vmap_` prefix — these are different things.

### Install

```bash
cd runner
python -m venv venv

# Windows
.\venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate

pip install -e .
```

After install, the `vardrrunner` command is available in the activated venv.

### Authenticate

```bash
vardrrunner login vardrmap
# Enter your VardrMap URL (e.g. https://your-railway-app.up.railway.app)
# Enter a vmap_ API key from Settings → API Keys
```

Config is saved to `~/.vardrmap/config.json`. The file stores the API key in plaintext — restrict access with `chmod 600 ~/.vardrmap/config.json` on Unix.

After logging in, run `vardrrunner status` to verify the setup:

```bash
vardrrunner status
```

This checks that the config file is present, the API key is valid, the backend is reachable, and that httpx/nuclei/subfinder are installed on PATH.

Send a heartbeat to mark the runner as online in the Bridge:

```bash
vardrrunner heartbeat
```

This reports your hostname, OS, runner version, and per-tool availability to VardrMap. The Bridge in the Jobs section shows the runner as online (green) for 5 minutes after the last heartbeat. Running `vardrrunner jobs run` sends a heartbeat automatically before processing any jobs.

### Daemon (continuous background worker)

Instead of running `vardrrunner jobs run` manually, start the daemon to continuously poll for jobs and send heartbeats in the background:

```bash
# Foreground (Ctrl+C to stop)
vardrrunner daemon start

# Background — writes PID to ~/.vardrrunner.pid, logs to ~/.vardrrunner.log
vardrrunner daemon start --detach

# Custom intervals
vardrrunner daemon start --poll-interval 10 --heartbeat-interval 30

# Log to a custom file
vardrrunner daemon start --detach --log-file /var/log/vardrrunner.log

# Check if running
vardrrunner daemon status

# Stop the background daemon
vardrrunner daemon stop
```

The daemon polls for pending jobs every 5 seconds (configurable) and sends a heartbeat every 60 seconds on a separate thread — heartbeats continue even during long-running jobs.

**Shutdown:** `daemon stop` removes the PID file, which the daemon checks every poll cycle — it finishes the current job and exits within one poll interval. This works identically on Windows and Linux/macOS (on POSIX, SIGTERM is also sent so an idle daemon exits immediately). Ctrl+C works in foreground mode on all platforms. Starting a second daemon while one is running is refused.

### Run tests

```bash
cd runner

# Windows
.\venv\Scripts\pytest.exe tests -v

# macOS / Linux
pytest tests -v
```

113 tests should pass. Tests mock all subprocess and HTTP calls — no tools or backend required.

### Prerequisites for `run` commands

VardrRunner invokes tools via PATH. Install them with Go (requires Go 1.21+):

```bash
go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest
go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
```

Or download pre-built binaries from the GitHub releases pages:

- **httpx** — https://github.com/projectdiscovery/httpx
- **nuclei** — https://github.com/projectdiscovery/nuclei
- **subfinder** — https://github.com/projectdiscovery/subfinder (required for `vardrrunner run subfinder`)

After installing, run `vardrrunner heartbeat` to verify that VardrMap can see which tools are available.

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
