"""Optional local authentication; all application authorization remains in deps."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth_methods import auth_methods
from db import get_db
from deps import get_current_user
from limiter import limiter
from local_auth import (
    COOKIE_NAME,
    PASSWORD_HASHER,
    check_transport,
    csrf_token,
    digest,
    issue_session,
    validate_password,
    verify_login,
)
from models import LocalSession

router = APIRouter()


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(max_length=128, repr=False)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128, repr=False)
    new_password: str = Field(max_length=128, repr=False)


@router.get("/auth/methods")
def methods(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"methods": auth_methods()}


@router.post("/auth/local/login")
@limiter.limit("10/minute")
def login(
    request: Request, response: Response, payload: Login, db: Session = Depends(get_db)
):
    check_transport(request, write=True)
    credential = verify_login(db, payload.username, payload.password)
    issue_session(db, credential.user_id, response, request.cookies.get(COOKIE_NAME))
    return {"authenticated": True}


@router.get("/auth/local/session")
def session(request: Request, response: Response, user=Depends(get_current_user)):
    if user.get("auth_method") != "local":
        raise HTTPException(status_code=401, detail="Unauthorized")
    response.headers["Cache-Control"] = "no-store"
    return {
        "authMethod": "local",
        "csrfToken": csrf_token(request.cookies[COOKIE_NAME]),
        "user": {
            "githubId": user["github_id"],
            "username": user["username"],
            "email": user["email"],
        },
    }


@router.post("/auth/local/logout")
def logout(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.get("auth_method") != "local":
        raise HTTPException(status_code=401, detail="Unauthorized")
    db.query(LocalSession).filter_by(
        token_hash=digest(request.cookies[COOKIE_NAME])
    ).delete()
    db.commit()
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}


@router.post("/auth/local/password")
@limiter.limit("5/minute")
def change_password(
    request: Request,
    response: Response,
    payload: PasswordChange,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.get("auth_method") != "local":
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    credential = verify_login(db, user["username"], payload.current_password)
    credential.password_hash = PASSWORD_HASHER.hash(payload.new_password)
    db.query(LocalSession).filter_by(user_id=user["github_id"]).delete()
    issue_session(db, user["github_id"], response)
    return {"authenticated": True}
