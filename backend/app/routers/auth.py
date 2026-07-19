"""Auth router: login, refresh (rotating, 90-day sliding expiry), logout, me."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.dependencies import CurrentUser, DbSession
from app.models.auth import RefreshToken, User
from app.utils.dt import utcnow
from app.utils.security import (
    create_access_token,
    generate_refresh_token,
    hash_token,
    verify_password,
)

router = APIRouter()


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    id: int
    username: str


def _issue_refresh_token(db, user_id: int) -> str:
    """Create and store a new opaque refresh token for the user."""
    settings = get_settings()
    raw = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_token(raw),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        )
    )
    return raw


@router.post("/login", response_model=TokenPair)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    user = db.scalar(select(User).where(User.username == form_data.username))
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    refresh_raw = _issue_refresh_token(db, user.id)
    db.commit()

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=refresh_raw,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(request: RefreshRequest, db: DbSession):
    db_token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(request.refresh_token))
    )
    if not db_token or not db_token.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Rotate: revoke the presented token, issue a fresh one (sliding 90-day expiry).
    db_token.revoked_at = utcnow()
    new_refresh_raw = _issue_refresh_token(db, db_token.user_id)
    db.commit()

    return TokenPair(
        access_token=create_access_token(db_token.user_id),
        refresh_token=new_refresh_raw,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: RefreshRequest, db: DbSession):
    db_token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(request.refresh_token))
    )
    if db_token and db_token.revoked_at is None:
        db_token.revoked_at = utcnow()
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(current_user: CurrentUser):
    return MeResponse(id=current_user.id, username=current_user.username)
