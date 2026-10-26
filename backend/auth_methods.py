"""One explicit provider policy for the existing backend."""

import os


def auth_methods() -> tuple[str, ...]:
    values = tuple(
        dict.fromkeys(
            part.strip()
            for part in os.getenv("VARDRMAP_AUTH_METHODS", "github").split(",")
        )
    )
    if not values or any(value not in {"github", "local"} for value in values):
        raise RuntimeError("VARDRMAP_AUTH_METHODS must contain github, local, or both")
    return values
