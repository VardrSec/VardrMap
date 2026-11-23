"""Backend authentication provider and signing configuration."""

import os


def backend_jwt_secret() -> str:
    secret = os.getenv("BACKEND_JWT_SECRET", "")
    if secret in {
        "change-me-to-a-long-random-string",
        "change-me-to-a-long-random-hex-string",
    }:
        raise RuntimeError(
            "Replace the example BACKEND_JWT_SECRET with a generated secret"
        )
    return secret


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
