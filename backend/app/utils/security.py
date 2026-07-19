"""Security utilities: bcrypt password hashing, JWT access tokens, opaque refresh tokens."""

import hashlib
import secrets
from datetime import timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings
from app.utils.dt import utcnow


# --- Passwords -------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


# --- JWT access tokens -----------------------------------------------------

def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


# --- Opaque refresh tokens -------------------------------------------------

def generate_refresh_token() -> str:
    """Opaque, URL-safe random refresh token (stored server-side only as a hash)."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a token for storage/lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
