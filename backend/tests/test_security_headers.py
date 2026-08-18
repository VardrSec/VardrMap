"""Security headers must be present on every response, not just successful ones.

The regression this guards: `CORSMiddleware` answers a preflight itself and
returns without calling the app beneath it. While `SecurityHeadersMiddleware`
was registered *inside* CORS, every `OPTIONS` response went out bare. The same
ordering bug meant any response CORS produced short-circuited the headers.

`SecurityHeadersMiddleware` is now outermost, so these assertions cover the paths
that never reach a route handler: preflight, auth failure, validation error, and
404.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

# Headers every response must carry, whatever the environment.
_ALWAYS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

_ORIGIN = "http://localhost:3000"


def _assert_hardened(res, label: str) -> None:
    for header, expected in _ALWAYS.items():
        assert res.headers.get(header) == expected, (
            f"{label} (HTTP {res.status_code}) is missing or has the wrong "
            f"{header!r}. Every response must carry the full header set — check "
            f"that SecurityHeadersMiddleware is still the outermost middleware "
            f"in main.py."
        )


# --------------------------------------------------------------------------- #
# Every response shape
# --------------------------------------------------------------------------- #

def test_normal_response_is_hardened(client, auth_headers, program_id):
    res = client.get(f"/engagements/{program_id}", headers=auth_headers)
    assert res.status_code == 200
    _assert_hardened(res, "a normal 200")


def test_unauthenticated_response_is_hardened(client, program_id):
    """An auth failure never reaches a route handler."""
    res = client.get(f"/engagements/{program_id}")
    assert res.status_code == 401
    _assert_hardened(res, "a 401")


def test_cross_user_404_is_hardened(client, other_headers, program_id):
    res = client.get(f"/engagements/{program_id}", headers=other_headers)
    assert res.status_code == 404
    _assert_hardened(res, "a cross-user 404")


def test_validation_error_is_hardened(client, auth_headers):
    res = client.post("/engagements", json={}, headers=auth_headers)
    assert res.status_code == 422
    _assert_hardened(res, "a 422 validation error")


def test_unknown_route_is_hardened(client):
    res = client.get("/no-such-route")
    assert res.status_code == 404
    _assert_hardened(res, "an unmatched route 404")


def test_health_endpoint_is_hardened(client):
    """Unauthenticated and outside every router."""
    res = client.get("/health")
    assert res.status_code == 200
    _assert_hardened(res, "the health endpoint")


# --------------------------------------------------------------------------- #
# Unhandled exceptions — ordering alone cannot cover these
# --------------------------------------------------------------------------- #

def test_unhandled_exception_returns_a_hardened_sanitized_500():
    """Starlette's ServerErrorMiddleware wraps every user middleware, so an
    exception escaping the app produces a 500 that SecurityHeaders can never
    stamp. It therefore catches the exception itself.

    Verified before the fix: the response was a bare 500 with no headers at all.
    """
    from fastapi.testclient import TestClient

    import main

    @main.app.get("/_test_unhandled_exception")
    def _boom():
        raise RuntimeError("token=super-secret internal detail")

    try:
        # raise_server_exceptions=False so the client returns the response
        # rather than re-raising, which is what a real client would see.
        local = TestClient(main.app, raise_server_exceptions=False)
        res = local.get("/_test_unhandled_exception")

        assert res.status_code == 500
        _assert_hardened(res, "an unhandled 500")
        # The body must not carry the exception.
        assert "super-secret" not in res.text
        assert "RuntimeError" not in res.text
        assert "Traceback" not in res.text
        assert res.json() == {"detail": "Internal Server Error"}
    finally:
        main.app.router.routes = [
            r for r in main.app.router.routes
            if getattr(r, "path", None) != "/_test_unhandled_exception"
        ]


# --------------------------------------------------------------------------- #
# CORS preflight — the case the ordering bug actually broke
# --------------------------------------------------------------------------- #

def test_cors_preflight_is_hardened(client, program_id):
    """CORSMiddleware short-circuits OPTIONS without calling the inner app.

    If SecurityHeadersMiddleware is ever moved back inside CORS this is the
    assertion that fails, and it fails for every preflight the browser sends.
    """
    res = client.options(
        f"/engagements/{program_id}",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert res.status_code == 200
    # Still a working preflight, not just a hardened one.
    assert res.headers.get("access-control-allow-origin") == _ORIGIN
    _assert_hardened(res, "a CORS preflight")


def test_cors_preflight_on_legacy_program_path_is_hardened(client, program_id):
    """The deprecated path is rewritten inside CORS, so it must be covered too."""
    res = client.options(
        f"/programs/{program_id}",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert res.status_code == 200
    _assert_hardened(res, "a CORS preflight on /programs")


def test_disallowed_origin_response_is_hardened(client, program_id):
    res = client.options(
        f"/engagements/{program_id}",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Whatever CORS decides, the response is still hardened.
    _assert_hardened(res, "a preflight from a disallowed origin")
    assert res.headers.get("access-control-allow-origin") != "https://evil.example"


# --------------------------------------------------------------------------- #
# HSTS is production-only
# --------------------------------------------------------------------------- #

def test_hsts_absent_in_test_env(client):
    """conftest sets ENV=test. Anything other than production must not pin HTTPS."""
    res = client.get("/health")
    assert "Strict-Transport-Security" not in res.headers


def _app_for_env(monkeypatch, env_value: str):
    """Reimport main under a given ENV and hand back a client for it.

    main.py reads ENV at import time, so the module has to be reloaded rather
    than patched. db/get_db overrides live on the old app object, so this client
    is only used for header assertions on routes that touch no database.
    """
    import main

    monkeypatch.setenv("ENV", env_value)
    reloaded = importlib.reload(main)
    return TestClient(reloaded.app), reloaded


@pytest.mark.parametrize("env_value", ["development", "test", "staging", "Production-typo"])
def test_hsts_absent_outside_production(monkeypatch, env_value):
    """Unrecognised environments fail to the safe side — no HSTS.

    The previous check was `ENV != "development"`, which stamped HSTS on test,
    staging and every typo.
    """
    original = os.environ.get("ENV", "test")
    try:
        test_client, _ = _app_for_env(monkeypatch, env_value)
        res = test_client.get("/health")
        assert res.status_code == 200
        assert "Strict-Transport-Security" not in res.headers, (
            f"ENV={env_value!r} must not receive HSTS — only an exact "
            f"'production' match should pin a browser to HTTPS."
        )
    finally:
        monkeypatch.setenv("ENV", original)
        importlib.reload(__import__("main"))


def test_hsts_present_in_production(monkeypatch):
    original = os.environ.get("ENV", "test")
    try:
        test_client, _ = _app_for_env(monkeypatch, "production")
        res = test_client.get("/health")
        assert res.status_code == 200
        hsts = res.headers.get("Strict-Transport-Security")
        assert hsts is not None, "production must send HSTS"
        assert "max-age=63072000" in hsts
        assert "includeSubDomains" in hsts
    finally:
        monkeypatch.setenv("ENV", original)
        importlib.reload(__import__("main"))
