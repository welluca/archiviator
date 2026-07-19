"""FastAPI dependencies: current user from Bearer access token, DB session,
and the capture actor (JWT OR capture-scope device token) for intake endpoints."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.auth import User
from app.services import device_tokens
from app.utils.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_exception

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise credentials_exception

    user = db.get(User, user_id)
    if user is None:
        raise credentials_exception
    return user


@dataclass(frozen=True)
class Actor:
    """Resolved capture-endpoint caller: the user plus HOW they authenticated.

    via_device_token lets endpoints that serve both audiences (GET
    /labels/resolve/{tag}) slim their response for a leaked-phone-token blast
    radius — a device token must never see purchase prices, serials or notes.
    """

    user: User
    via_device_token: bool


async def get_capture_actor(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> Actor:
    """JWT user OR capture-scope device-token owner.

    Applied ONLY to the three capture endpoints (POST /intake/capture,
    GET /labels/resolve/{tag}, POST /entities/{id}/attachments). Everything
    else keeps get_current_user, which rejects 'adt_' bearers outright —
    that asymmetry IS the device-token scope wall.
    """
    if token.startswith(device_tokens.TOKEN_PREFIX):
        device = device_tokens.authenticate(db, token)
        user = db.get(User, device.user_id) if device is not None else None
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, revoked or expired device token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return Actor(user=user, via_device_token=True)
    return Actor(user=await get_current_user(token, db), via_device_token=False)


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
