"""M3 attachments: attachment table + entity.cover_attachment_id.

The entity column is added via batch_alter_table: on SQLite that recreates the
table (copying every existing row — the real DB has live data), which is the
only way to attach the new FK. Alembic's env engine leaves PRAGMA foreign_keys
at its OFF default, so the recreate cannot trip over the self-referential
parent_id FK or the new attachment FK cycle.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("thumb_path", sa.Text(), nullable=True),
        sa.Column("display_path", sa.Text(), nullable=True),
        sa.Column("mime", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("drive_file_id", sa.Text(), nullable=True),
        sa.Column("drive_name", sa.Text(), nullable=True),
        sa.Column("drive_mime", sa.Text(), nullable=True),
        sa.Column("drive_modified_time", sa.Text(), nullable=True),
        sa.Column("drive_md5", sa.Text(), nullable=True),
        sa.Column("drive_status", sa.Text(), nullable=False, server_default="ok"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "type IN ('photo','document','drive_link')", name="ck_attachment_type"
        ),
        sa.CheckConstraint(
            "drive_status IN ('ok','missing','changed')", name="ck_attachment_drive_status"
        ),
        sa.CheckConstraint(
            "(type IN ('photo','document') AND file_path IS NOT NULL AND drive_file_id IS NULL)"
            " OR (type = 'drive_link' AND drive_file_id IS NOT NULL AND file_path IS NULL)",
            name="ck_attachment_storage",
        ),
    )
    op.create_index("ix_attachment_entity_id", "attachment", ["entity_id"])
    op.create_index(
        "ix_attachment_content_hash",
        "attachment",
        ["content_hash"],
        sqlite_where=sa.text("content_hash IS NOT NULL"),
    )
    op.create_index(
        "ix_attachment_drive_file_id",
        "attachment",
        ["drive_file_id"],
        sqlite_where=sa.text("drive_file_id IS NOT NULL"),
    )

    with op.batch_alter_table("entity") as batch_op:
        batch_op.add_column(sa.Column("cover_attachment_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_entity_cover_attachment",
            "attachment",
            ["cover_attachment_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("entity") as batch_op:
        batch_op.drop_constraint("fk_entity_cover_attachment", type_="foreignkey")
        batch_op.drop_column("cover_attachment_id")
    op.drop_index("ix_attachment_drive_file_id", table_name="attachment")
    op.drop_index("ix_attachment_content_hash", table_name="attachment")
    op.drop_index("ix_attachment_entity_id", table_name="attachment")
    op.drop_table("attachment")
