"""JWT auth middleware — missing, invalid, expired, and wrong-audience tokens."""
from datetime import timedelta

from tests.conftest import mint_token


def test_no_token_returns_401(client):
    res = client.get("/me")
    assert res.status_code == 401


def test_empty_bearer_returns_401(client):
    res = client.get("/me", headers={"Authorization": "Bearer "})
    assert res.status_code == 401


def test_garbage_token_returns_401(client):
    res = client.get("/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert res.status_code == 401


def test_expired_token_returns_401(client):
    token = mint_token(expire_delta=timedelta(seconds=-1))
    res = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_wrong_audience_returns_401(client):
    from jose import jwt
    token = jwt.encode(
        {"sub": "gh_user1", "aud": "wrong-audience", "iss": "vardrmap-frontend"},
        "test-secret-key-for-pytest-needs-32-chars!!",
        algorithm="HS256",
    )
    res = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_valid_token_returns_user(client, auth_headers):
    res = client.get("/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["github_id"] == "gh_user1"
    assert data["username"] == "user1"
