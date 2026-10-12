"""Connection policy shared by the application, migrations and database tests."""

from sqlalchemy.engine import make_url


def normalize_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1).replace(
        "postgres://", "postgresql+psycopg://", 1
    )


def connection_args(url: str) -> dict:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        return {}
    # Keep TLS required by default; local/CI instances can explicitly select
    # sslmode in their URL. Append UTC last so URL options cannot override it.
    options = parsed.query.get("options", "")
    return {
        "sslmode": parsed.query.get("sslmode", "require"),
        "options": f"{options} -c timezone=UTC".strip(),
    }
