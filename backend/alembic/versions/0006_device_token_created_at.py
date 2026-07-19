"""M7 device_token: created_at column (listed by GET /auth/device-tokens).

SQLite forbids non-constant defaults in ADD COLUMN, so the column is added
nullable and backfilled; the ORM default (utcnow) fills every future insert.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-19

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("device_token", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE device_token SET created_at = datetime('now') WHERE created_at IS NULL")


def downgrade() -> None:
    op.drop_column("device_token", "created_at")
