"""
Application logging + optional error tracking.

`configure_logging()` is called once at startup (from main.py). It routes logs
to stdout — which Railway captures as the service log — at a level taken from the
`LOG_LEVEL` env var, and, when `SENTRY_DSN` is set, initializes Sentry for error
aggregation and alerting.

Both are zero-config friendly: with no env vars set you get INFO-level stdout
logging and no Sentry. Sentry is fully optional — the `sentry_sdk` import only
happens when a DSN is present, so the package is not required unless you use it.

App code logs under the ``vardrmap`` logger namespace (e.g.
``logging.getLogger("vardrmap.notifications")``).
"""
import logging
import os
import sys

# Module-level guard so repeated imports / calls don't stack handlers or
# re-initialize Sentry.
_CONFIGURED = False

_APP_LOGGER = "vardrmap"


def configure_logging() -> None:
    """Idempotently configure root logging and, if configured, Sentry."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):  # unknown LOG_LEVEL → fall back to INFO
        level = logging.INFO
        level_name = "INFO"

    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger(_APP_LOGGER).setLevel(level)

    _init_sentry()
    _CONFIGURED = True
    logging.getLogger(_APP_LOGGER).info("logging configured at level %s", level_name)


def _init_sentry() -> None:
    """Initialize Sentry when SENTRY_DSN is set. No-op (with a warning if the SDK
    is missing) otherwise, so the dependency stays optional."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger(_APP_LOGGER).warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; skipping Sentry init"
        )
        return

    env = os.getenv("ENV") or os.getenv("RAILWAY_ENVIRONMENT_NAME", "development")
    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        # Tracing is opt-in and off by default — errors are captured regardless.
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        send_default_pii=False,
    )
    logging.getLogger(_APP_LOGGER).info("Sentry initialized for environment %s", env)
