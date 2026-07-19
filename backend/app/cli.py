"""Archiviator CLI: user management.

Usage:
    python -m app.cli create-user <username> [--password PW]
    python -m app.cli change-password <username> [--password PW]
"""

import argparse
import getpass
import sys

from sqlalchemy import select


def create_user(username: str, password: str) -> int:
    """Create a user; returns the new user id. Raises ValueError if username taken."""
    from app.database import get_sessionmaker
    from app.models.auth import User
    from app.utils.security import hash_password

    with get_sessionmaker()() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing:
            raise ValueError(f"User '{username}' already exists")
        user = User(username=username, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def change_password(username: str, password: str) -> None:
    """Set a new password for an existing user. Raises ValueError if not found."""
    from app.database import get_sessionmaker
    from app.models.auth import User
    from app.utils.security import hash_password

    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            raise ValueError(f"User '{username}' not found")
        user.password_hash = hash_password(password)
        db.commit()


def _prompt_password(confirm: bool = True) -> str:
    pw = getpass.getpass("Password: ")
    if not pw:
        print("Password must not be empty.", file=sys.stderr)
        sys.exit(1)
    if confirm:
        pw2 = getpass.getpass("Confirm password: ")
        if pw != pw2:
            print("Passwords do not match.", file=sys.stderr)
            sys.exit(1)
    return pw


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="archiviator", description="Archiviator user management")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-user", help="Create a new user")
    p_create.add_argument("username")
    p_create.add_argument("--password", help="Password (omit to be prompted)")

    p_change = sub.add_parser("change-password", help="Change an existing user's password")
    p_change.add_argument("username")
    p_change.add_argument("--password", help="New password (omit to be prompted)")

    args = parser.parse_args(argv)

    # Ensure schema exists before touching the DB.
    from app.database import run_migrations

    run_migrations()

    password = args.password or _prompt_password()

    try:
        if args.command == "create-user":
            user_id = create_user(args.username, password)
            print(f"Created user '{args.username}' (id={user_id})")
        elif args.command == "change-password":
            change_password(args.username, password)
            print(f"Password updated for '{args.username}'")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
