from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared limiter instance. Import this in routers that need per-route overrides.
# app.state.limiter is set in main.py so SlowAPIMiddleware can pick it up.
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
