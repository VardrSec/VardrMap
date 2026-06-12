import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared limiter instance. Import this in routers that need per-route overrides.
# app.state.limiter is set in main.py so SlowAPIMiddleware can pick it up.
# Disabled under pytest — the whole suite shares one client IP and would trip
# the global limit; rate-limiting behavior itself isn't what tests exercise.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    enabled=os.getenv("ENV") != "test",
)
