"""Device-token service (M7): capture-scope bearer tokens for phone/Shortcuts clients.

Plaintext tokens are 'adt_' + token_urlsafe(32), shown exactly once at creation;
only the sha256 hex digest is stored (same rule as refresh tokens).
authenticate() is the hot path behind get_capture_actor: it re-checks
revocation/expiry/scope on every call and touches last_used_at at most once a
minute so a burst of captures does not write a row per shot.

Domain errors reuse tree.NotFoundError (404); routers translate.
"""

import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import DeviceToken
from app.services.tree import NotFoundError
from app.utils.dt import utcnow
from app.utils.security import hash_token

TOKEN_PREFIX = "adt_"
LAST_USED_TOUCH_SECONDS = 60


def create_token(
    db: Session, user_id: int, label: str, expires_days: int | None = None
) -> tuple[DeviceToken, str]:
    """Create a capture-scope token; returns (row, plaintext). The plaintext is
    never stored and never retrievable again. expires_days=None (default) mints
    a non-expiring token; authenticate() enforces expires_at on every call."""
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = DeviceToken(
        user_id=user_id,
        label=label,
        token_hash=hash_token(plaintext),
        expires_at=utcnow() + timedelta(days=expires_days) if expires_days else None,
    )
    db.add(token)
    db.commit()
    return token, plaintext


def list_tokens(db: Session, user_id: int) -> list[DeviceToken]:
    """The user's tokens, newest first (hashes only — plaintext is long gone)."""
    stmt = (
        select(DeviceToken)
        .where(DeviceToken.user_id == user_id)
        .order_by(DeviceToken.created_at.desc(), DeviceToken.id.desc())
    )
    return list(db.scalars(stmt))


def revoke_token(db: Session, user_id: int, token_id: int) -> None:
    """Revoke (idempotent). Tokens of OTHER users read as not found, never 403 —
    the id must not leak existence."""
    token = db.get(DeviceToken, token_id)
    if token is None or token.user_id != user_id:
        raise NotFoundError(f"Device token {token_id} not found")
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        db.commit()


def authenticate(db: Session, plaintext: str) -> DeviceToken | None:
    """The unrevoked, unexpired, capture-scope token matching plaintext, or None.
    Touches last_used_at (own commit), throttled to once per minute."""
    token = db.scalar(
        select(DeviceToken).where(DeviceToken.token_hash == hash_token(plaintext))
    )
    if token is None or token.revoked_at is not None:
        return None
    now = utcnow()
    if token.expires_at is not None and token.expires_at <= now:
        return None
    if "capture" not in token.scopes.split(","):
        return None
    if (
        token.last_used_at is None
        or (now - token.last_used_at).total_seconds() >= LAST_USED_TOUCH_SECONDS
    ):
        token.last_used_at = now
        db.commit()
    return token
