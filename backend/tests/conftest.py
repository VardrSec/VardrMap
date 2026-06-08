import os

# Set env vars BEFORE any app imports so db.py and deps.py pick them up.
# load_dotenv() in db.py uses override=False, so these take precedence over .env.
os.environ["DATABASE_URL"] = "sqlite:///./test_vardrmap.db"
os.environ["BACKEND_JWT_SECRET"] = "test-secret-key-for-pytest-needs-32-chars!!"
os.environ["ENV"] = "test"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base, get_db
from main import app

_TEST_DB = "sqlite:///./test_vardrmap.db"
_engine = create_engine(_TEST_DB, connect_args={"check_same_thread": False})
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

Base.metadata.create_all(bind=_engine)


def _override_get_db():
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

_SECRET = "test-secret-key-for-pytest-needs-32-chars!!"


def mint_token(
    github_id: str = "gh_user1",
    username: str = "testuser",
    expire_delta: timedelta = timedelta(hours=1),
) -> str:
    exp = datetime.now(timezone.utc) + expire_delta
    return jwt.encode(
        {
            "sub": github_id,
            "username": username,
            "email": f"{username}@example.com",
            "aud": "vardrmap-backend",
            "iss": "vardrmap-frontend",
            "exp": exp,
        },
        _SECRET,
        algorithm="HS256",
    )


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    _engine.dispose()


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {mint_token('gh_user1', 'user1')}"}


@pytest.fixture
def other_headers() -> dict:
    """Headers for a second, unrelated user — used to verify BOLA protection."""
    return {"Authorization": f"Bearer {mint_token('gh_user2', 'user2')}"}


@pytest.fixture
def program_id(client, auth_headers) -> str:
    """Creates a fresh program owned by user1, yields its ID, then deletes it."""
    res = client.post("/programs", json={"name": "Test Program"}, headers=auth_headers)
    assert res.status_code == 200
    pid = res.json()["id"]
    yield pid
    client.delete(f"/programs/{pid}", headers=auth_headers)
