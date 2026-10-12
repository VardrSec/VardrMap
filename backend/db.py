import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from database_options import connection_args, normalize_url

ENV_PATH = Path(__file__).resolve().with_name(".env")
load_dotenv(dotenv_path=ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError(f"DATABASE_URL is not set. Looked in: {ENV_PATH}")

# Railway (and most Postgres providers) give a postgresql:// URL which SQLAlchemy
# maps to psycopg2 by default. We use psycopg3 (psycopg[binary]), so rewrite the
# scheme to opt into the right driver without touching the rest of the URL.
# SQLite URLs (used in tests) are left untouched and don't get sslmode.
DATABASE_URL = normalize_url(DATABASE_URL)
_connect_args = connection_args(DATABASE_URL)
# pool_pre_ping validates connections before use — Railway closes idle Postgres
# connections, and without this the first request after a quiet period 500s.
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
