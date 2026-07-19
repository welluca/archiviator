"""Datetime helpers: naive-UTC convention for DB storage."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (SQLite-friendly, comparable to stored values)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
