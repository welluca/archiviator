"""M9 Google Drive: drive_account (singleton, seeded) + scan_inbox.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-19

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drive_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("scans_folder_id", sa.Text(), nullable=True),
        sa.Column("scans_folder_name", sa.Text(), nullable=True),
        sa.Column("backup_folder_id", sa.Text(), nullable=True),
        sa.Column("poll_interval_min", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("backup_upload_enabled", sa.Boolean(), nullable=False, server_default="0"),
        # TEXT timestamps on purpose: they pair with Drive's RFC3339 strings.
        sa.Column("last_poll_at", sa.Text(), nullable=True),
        sa.Column("last_backup_upload_at", sa.Text(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_drive_account_single"),
    )
    # The one and only row — code reads/writes drive_account id=1 unconditionally.
    op.execute(
        "INSERT INTO drive_account (id, poll_interval_min, backup_upload_enabled)"
        " VALUES (1, 15, 0)"
    )

    op.create_table(
        "scan_inbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("drive_file_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=True),
        sa.Column("modified_time", sa.Text(), nullable=True),
        sa.Column("md5", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="new"),
        sa.Column(
            "attachment_id",
            sa.Integer(),
            sa.ForeignKey("attachment.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("status IN ('new','attached','ignored')", name="ck_scan_inbox_status"),
    )
    op.create_index("ix_scan_inbox_drive_file_id", "scan_inbox", ["drive_file_id"], unique=True)
    op.create_index("ix_scan_inbox_status", "scan_inbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_scan_inbox_status", table_name="scan_inbox")
    op.drop_index("ix_scan_inbox_drive_file_id", table_name="scan_inbox")
    op.drop_table("scan_inbox")
    op.drop_table("drive_account")
