"""Auth router: login, refresh (rotating, 90-day sliding expiry), logout, me,
and device tokens (M7): capture-scope bearers for phone clients, JWT-only CRUD."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.config import get_settings
from app.dependencies import CurrentUser, DbSession
from app.models.auth import RefreshToken, User
from app.services import device_tokens as device_tokens_svc
from app.services.tree import NotFoundError
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


# --- device tokens (M7) -------------------------------------------------------


class DeviceTokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    # null/omitted = non-expiring (a kitchen iPad outlives any sane TTL).
    expires_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("label")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label must not be blank")
        return v


class DeviceTokenCreated(BaseModel):
    id: int
    label: str
    token: str  # plaintext, shown exactly ONCE


class DeviceTokenOut(BaseModel):
    id: int
    label: str
    # Nullable: migration 0006 added the column nullable (SQLite ADD COLUMN
    # forbids non-constant defaults) — mirror that instead of lying to clients.
    created_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


@router.post(
    "/device-tokens", response_model=DeviceTokenCreated, status_code=status.HTTP_201_CREATED
)
async def create_device_token(
    payload: DeviceTokenCreate, current_user: CurrentUser, db: DbSession
):
    """Mint a capture-scope device token. The plaintext appears only in THIS
    response — the listing never returns it (sha256 stored)."""
    token, plaintext = device_tokens_svc.create_token(
        db, current_user.id, payload.label, expires_days=payload.expires_days
    )
    return DeviceTokenCreated(id=token.id, label=token.label, token=plaintext)


@router.get("/device-tokens", response_model=list[DeviceTokenOut])
async def list_device_tokens(current_user: CurrentUser, db: DbSession):
    return [
        DeviceTokenOut(
            id=t.id,
            label=t.label,
            created_at=t.created_at,
            last_used_at=t.last_used_at,
            revoked_at=t.revoked_at,
        )
        for t in device_tokens_svc.list_tokens(db, current_user.id)
    ]


@router.post("/device-tokens/{token_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device_token(token_id: int, current_user: CurrentUser, db: DbSession):
    try:
        device_tokens_svc.revoke_token(db, current_user.id, token_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
