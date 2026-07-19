"""Initial M1 schema: user, refresh_token, device_token, meta (+ seed meta rows).

Revision ID: 0001
Revises:
Create Date: 2026-07-19

"""
import uuid

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_username", "user", ["username"], unique=True)

    op.create_table(
        "refresh_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_refresh_token_user_id", "refresh_token", ["user_id"])
    op.create_index("ix_refresh_token_token_hash", "refresh_token", ["token_hash"], unique=True)

    op.create_table(
        "device_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False, server_default="capture"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_device_token_user_id", "device_token", ["user_id"])
    op.create_index("ix_device_token_token_hash", "device_token", ["token_hash"], unique=True)

    op.create_table(
        "meta",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
    )

    meta = sa.table("meta", sa.column("key", sa.Text()), sa.column("value", sa.Text()))
    op.bulk_insert(
        meta,
        [
            {"key": "base_url", "value": "https://threadripper.tail3670c0.ts.net"},
            {"key": "default_currency", "value": "EUR"},
            {"key": "install_id", "value": uuid.uuid4().hex},
            {"key": "schema_note", "value": "m1"},
        ],
    )


def downgrade() -> None:
    op.drop_table("meta")
    op.drop_index("ix_device_token_token_hash", table_name="device_token")
    op.drop_index("ix_device_token_user_id", table_name="device_token")
    op.drop_table("device_token")
    op.drop_index("ix_refresh_token_token_hash", table_name="refresh_token")
    op.drop_index("ix_refresh_token_user_id", table_name="refresh_token")
    op.drop_table("refresh_token")
    op.drop_index("ix_user_username", table_name="user")
    op.drop_table("user")
