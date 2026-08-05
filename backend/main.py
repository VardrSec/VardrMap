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
from routers import apikeys, authorizations, clients, engagements, findings, imports, jobs, manual_tests, members, radar, recon, reports, runner, scans, schedules, scope, services, settings, submissions

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
# Legacy path alias
# -----------------------------------------------------------------------------

class LegacyProgramPathMiddleware:
    """Serve the retired `/programs/*` paths from the `/engagements/*` routes.

    The resource was renamed when VardrMap widened from bug bounty work to
    professional engagements. VardrRunner lives in its own repository and
    deploys separately, and personal API keys are used from Burp and ad-hoc
    scripts — so the old paths cannot disappear the moment this backend ships.

    Rewriting the path here rather than registering every route twice keeps the
    OpenAPI schema and the docs contract describing one set of routes, and
    preserves the router registration order that lets runner-scoped keys read
    engagement data (see the Routers section below). Retiring the alias later
    means deleting this class and its one `add_middleware` line.
    """

    _OLD = "/programs"
    _NEW = "/engagements"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            # Exact match or a whole path segment — never a prefix like /programsfoo.
            if path == self._OLD or path.startswith(self._OLD + "/"):
                rewritten = self._NEW + path[len(self._OLD):]
                scope = dict(scope)
                scope["path"] = rewritten
                if scope.get("raw_path"):
                    scope["raw_path"] = rewritten.encode()
        await self.app(scope, receive, send)


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
# Added last so it runs first: the path is rewritten before routing, rate
# limiting, or anything else inspects it.
app.add_middleware(LegacyProgramPathMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# -----------------------------------------------------------------------------
# Identity — accessible with any valid token (runner-scoped or full)
# Must live outside the engagements router so it doesn't inherit require_full_scope.
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

# Runner router registered first so its GET /engagements/{id} and
# GET /engagements/{id}/scope routes match before engagements.router's copies,
# allowing runner-scoped keys to read engagement data for job execution.
app.include_router(imports.router)
app.include_router(jobs.router)
app.include_router(runner.router)

app.include_router(apikeys.router,      dependencies=_full)
app.include_router(engagements.router,  dependencies=_full)
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
app.include_router(clients.router,        dependencies=_full)
app.include_router(authorizations.router, dependencies=_full)

# -----------------------------------------------------------------------------
# Health / root
# -----------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"message": "VardrMap API is running", "environment": ENV}


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": ENV}
