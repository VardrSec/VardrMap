import logging
import os

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from db import Base, engine
from deps import get_current_user, require_full_scope
from limiter import limiter
from logging_config import configure_logging
from routers import api_surface, apikeys, assets, authorizations, clients, engagements, evidence, findings, imports, jobs, manual_tests, members, radar, recon, reports, runner, scan_profiles, scans, schedules, scope, services, settings, test_cases

ENV = os.getenv("ENV") or os.getenv("RAILWAY_ENVIRONMENT_NAME", "development")

# Production is named explicitly rather than inferred as "not development".
# HSTS is the reason this matters: `ENV != "development"` also matched "test",
# "staging", and any typo, so a browser hitting a non-HTTPS deployment could be
# pinned to HTTPS for two years. Naming production means an unrecognised ENV
# fails to the safe side — no HSTS — instead of stamping it everywhere.
IS_PRODUCTION = ENV.strip().lower() == "production"

# Route logs to stdout (and Sentry, if SENTRY_DSN is set) before anything else
# runs, so startup and import-time problems are captured too.
configure_logging()
logger = logging.getLogger("vardrmap")

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
        try:
            response = await call_next(request)
        except Exception:
            # An exception escaping the app is turned into a 500 by Starlette's
            # ServerErrorMiddleware, which sits *outside* every user middleware —
            # so that response can never be stamped from here. Registering an
            # `Exception` handler on the app does not help either: it is invoked
            # by that same outer middleware.
            #
            # Producing the 500 here instead keeps it inside this middleware, so
            # it carries the same headers as every other response. The body is a
            # fixed string: an unhandled exception is exactly the case where
            # detail is most likely to leak internals.
            logger.exception("Unhandled exception while handling %s %s",
                             request.method, request.url.path)
            response = JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # CSP for a pure JSON API — it serves no scripts, styles, images or
        # frames, so everything is denied and there is nothing to loosen.
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        # HSTS in production only. See IS_PRODUCTION — pinning a browser to
        # HTTPS for two years is not something to do on a guess.
        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response

# -----------------------------------------------------------------------------
# App + middleware stack
# -----------------------------------------------------------------------------

app = FastAPI(title="VardrMap API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Starlette applies middleware in reverse: the LAST one added is the OUTERMOST,
# so this block reads inside-out. The resulting chain is
#
#     SecurityHeaders -> CORS -> LegacyProgramPath -> SlowAPI -> app
#
# SecurityHeaders must be outermost. CORSMiddleware answers a preflight itself
# and returns without ever calling the app beneath it, so anything registered
# inside CORS never sees an OPTIONS request — which is how preflight responses
# previously went out with no security headers at all. Being outermost also
# means the headers survive paths that never reach a route handler: auth
# failures, validation errors, rate-limit rejections, and unmatched routes.
#
# Unhandled exceptions are the one case ordering alone cannot cover, because
# Starlette's ServerErrorMiddleware wraps every user middleware. SecurityHeaders
# catches them itself and returns a sanitized 500 — see its dispatch().
#
# LegacyProgramPath stays outside SlowAPI so rate limiting keys on the rewritten
# `/engagements/*` path rather than the deprecated `/programs/*` one.
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(LegacyProgramPathMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(SecurityHeadersMiddleware)

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
app.include_router(assets.router,       dependencies=_full)
app.include_router(api_surface.router,  dependencies=_full)
app.include_router(evidence.router,     dependencies=_full)
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
app.include_router(schedules.router,    dependencies=_full)
app.include_router(scan_profiles.router, dependencies=_full)
app.include_router(test_cases.router,    dependencies=_full)
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
