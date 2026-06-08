import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

ENV_PATH = Path(__file__).resolve().with_name(".env")
load_dotenv(dotenv_path=ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError(f"DATABASE_URL is not set. Looked in: {ENV_PATH}")

# Railway (and most Postgres providers) give a postgresql:// URL which SQLAlchemy
# maps to psycopg2 by default. We use psycopg3 (psycopg[binary]), so rewrite the
# scheme to opt into the right driver without touching the rest of the URL.
# SQLite URLs (used in tests) are left untouched and don't get sslmode.
_is_postgres = DATABASE_URL.startswith(("postgresql://", "postgres://", "postgresql+psycopg://"))
if _is_postgres:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

_connect_args = {"sslmode": "require"} if _is_postgres else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()