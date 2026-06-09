# Development

## Prerequisites

- Python 3.12+ (project runs on 3.14)
- Node.js 20+
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

All 42 tests should pass. There are no frontend tests at this time.

### Test coverage areas

| File | What it tests |
|---|---|
| `tests/test_programs.py` | Program CRUD, ownership isolation (BOLA) |
| `tests/test_findings.py` | Finding CRUD, cross-program access denial |
| `tests/test_reports.py` | Report CRUD, cross-program access denial |
| `tests/test_manual_tests.py` | Manual test CRUD |
| `tests/test_scope.py` | Scope item add/delete |
| `tests/test_imports.py` | File upload parsing, extension/size validation |
| `tests/test_recon.py` | Recon list and clear |
| `tests/test_scans.py` | Scan list, status update, bulk update, pagination |
| `tests/test_apikeys.py` | Key generation, API key auth at `/me`, revocation, BOLA isolation, max-key limit |

---

## Database Migrations

Migrations use Alembic. The migration chain is:

```
0001_baseline  →  0002_add_created_at  →  0003_add_api_keys
```

**Fresh deployment:** `main.py` calls `Base.metadata.create_all()` on startup, which creates all tables from the current model definitions. For Alembic to track this correctly, stamp the baseline:
```bash
alembic stamp head
```

**Existing deployment (pre-Alembic):** Same — stamp the baseline without running migrations:
```bash
alembic stamp head
```

**Apply pending migrations:**
```bash
alembic upgrade head
```

**Create a new migration after changing `models.py`:**
```bash
alembic revision --autogenerate -m "short description"
```

Review the generated file in `migrations/versions/` before applying — autogenerate can miss some changes (e.g. column type changes, custom constraints).

**Check current revision:**
```bash
alembic current
```

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
