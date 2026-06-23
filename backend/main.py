import os

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from db import Base, engine
from deps import get_current_user, require_full_scope
from limiter import limiter
from logging_config import configure_logging
from routers import apikeys, findings, imports, jobs, manual_tests, members, programs, radar, recon, reports, runner, scans, schedules, scope, services, settings, submissions

ENV = os.getenv("ENV") or os.getenv("RAILWAY_ENVIRONMENT_NAME", "development")

# Route logs to stdout (and Sentry, if SENTRY_DSN is set) before anything else
# runs, so startup and import-time problems are captured too.
configure_logging()

# In production, schema migrations are handled by Alembic (start.sh runs
# `alembic upgrade head` before uvicorn). create_all is kept for local dev
# and isolated SQLite tests only — it must never run in production.
if ENV in ("development", "test"):
    Base.metadata.create_all(bind=engine)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,https://vardr-map.vercel.app",
    ).split(",")
    if origin.strip()
]

# -----------------------------------------------------------------------------
# Security headers middleware
# -----------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # CSP for a pure API — no scripts, frames, or resources needed
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        # HSTS only in production — avoids breaking local HTTP dev
        if ENV != "development":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response

# -----------------------------------------------------------------------------
# App + middleware stack
# -----------------------------------------------------------------------------

app = FastAPI(title="VardrMap API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware is applied in reverse order — SlowAPI and CORS must wrap the app,
# SecurityHeaders runs last so it stamps every response regardless of origin.
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# -----------------------------------------------------------------------------
# Identity — accessible with any valid token (runner-scoped or full)
# Must live outside the programs router so it doesn't inherit require_full_scope.
# -----------------------------------------------------------------------------

@app.get("/me")
def me(current_user: dict[str, str] = Depends(get_current_user)):
    return current_user


# -----------------------------------------------------------------------------
# Routers
# Runner-accessible routers (jobs, imports, runner) do NOT get require_full_scope.
# All other routers are restricted to full-scope keys (browser JWTs always pass).
# -----------------------------------------------------------------------------

_full = [Depends(require_full_scope)]

# Runner router registered first so its GET /programs/{id} and
# GET /programs/{id}/scope routes match before programs.router's copies,
# allowing runner-scoped keys to read program data for job execution.
app.include_router(imports.router)
app.include_router(jobs.router)
app.include_router(runner.router)

app.include_router(apikeys.router,      dependencies=_full)
app.include_router(programs.router,     dependencies=_full)
app.include_router(members.router,      dependencies=_full)
app.include_router(scope.router,        dependencies=_full)
app.include_router(recon.router,        dependencies=_full)
app.include_router(scans.router,        dependencies=_full)
app.include_router(manual_tests.router, dependencies=_full)
app.include_router(findings.router,     dependencies=_full)
app.include_router(reports.router,      dependencies=_full)
app.include_router(services.router)
app.include_router(radar.router,        dependencies=_full)
app.include_router(submissions.router,  dependencies=_full)
app.include_router(schedules.router,    dependencies=_full)
app.include_router(settings.router,     dependencies=_full)

# -----------------------------------------------------------------------------
# Health / root
# -----------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"message": "VardrMap API is running", "environment": ENV}


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": ENV}
