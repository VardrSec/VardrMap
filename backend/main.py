import os

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from db import Base, engine
from limiter import limiter
from routers import apikeys, findings, imports, jobs, manual_tests, programs, radar, recon, reports, runner, scans, schedules, scope, services, settings, submissions

ENV = os.getenv("ENV") or os.getenv("RAILWAY_ENVIRONMENT_NAME", "development")

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
# Routers
# -----------------------------------------------------------------------------

app.include_router(apikeys.router)
app.include_router(programs.router)
app.include_router(scope.router)
app.include_router(recon.router)
app.include_router(scans.router)
app.include_router(manual_tests.router)
app.include_router(findings.router)
app.include_router(reports.router)
app.include_router(imports.router)
app.include_router(jobs.router)
app.include_router(runner.router)
app.include_router(services.router)
app.include_router(radar.router)
app.include_router(submissions.router)
app.include_router(schedules.router)
app.include_router(settings.router)

# -----------------------------------------------------------------------------
# Health / root
# -----------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"message": "VardrMap API is running", "environment": ENV}


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": ENV}
