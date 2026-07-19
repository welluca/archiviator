"""M2 entity tree: entity table, indexes, seeded Inbox root.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-19

"""
from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subtype", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("path", sa.Text(), nullable=False, server_default=""),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("breadcrumb", sa.Text(), nullable=False, server_default=""),
        sa.Column("asset_tag", sa.Text(), nullable=True, unique=True),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="1"),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("is_consumable", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Float(), nullable=True),
        sa.Column("purchase_date", sa.Text(), nullable=True),
        sa.Column("purchase_price", sa.Numeric(), nullable=True),
        sa.Column("purchase_from", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("current_value", sa.Numeric(), nullable=True),
        sa.Column("insured", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("warranty_expires", sa.Text(), nullable=True),
        sa.Column("warranty_lifetime", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("warranty_notes", sa.Text(), nullable=True),
        sa.Column("serial_number", sa.Text(), nullable=True),
        sa.Column("model_number", sa.Text(), nullable=True),
        sa.Column("manufacturer", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sold_date", sa.Text(), nullable=True),
        sa.Column("sold_to", sa.Text(), nullable=True),
        sa.Column("sold_price", sa.Numeric(), nullable=True),
        sa.Column("sold_notes", sa.Text(), nullable=True),
        sa.Column("import_ref", sa.Text(), nullable=True),
        sa.Column("draft", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('space','furniture','container','item')", name="ck_entity_kind"
        ),
    )
    op.create_index("ix_entity_parent_id", "entity", ["parent_id"])
    op.create_index("ix_entity_path", "entity", ["path"])
    op.create_index("ix_entity_kind", "entity", ["kind"])
    op.create_index("ix_entity_name", "entity", ["name"])
    op.create_index("ix_entity_import_ref", "entity", ["import_ref"])
    op.create_index("ix_entity_draft", "entity", ["draft"], sqlite_where=sa.text("draft = 1"))

    # Seed the Inbox root (renamable, but never movable or deletable).
    conn = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
    conn.execute(
        sa.text(
            "INSERT INTO entity (kind, subtype, name, depth, breadcrumb, created_at, updated_at) "
            "VALUES ('space', 'inbox', 'Inbox', 0, 'Inbox', :now, :now)"
        ),
        {"now": now},
    )
    conn.execute(
        sa.text(
            "UPDATE entity SET path = '/' || id || '/' "
            "WHERE kind = 'space' AND subtype = 'inbox' AND parent_id IS NULL"
        )
    )
    # Protection is keyed to this row's id (not its mutable subtype): tree.py
    # reads meta.inbox_entity_id to refuse move/delete/archive.
    conn.execute(
        sa.text(
            "INSERT INTO meta (key, value) "
            "SELECT 'inbox_entity_id', CAST(id AS TEXT) FROM entity "
            "WHERE kind = 'space' AND subtype = 'inbox' AND parent_id IS NULL"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM meta WHERE key = 'inbox_entity_id'"))
    op.drop_index("ix_entity_draft", table_name="entity")
    op.drop_index("ix_entity_import_ref", table_name="entity")
    op.drop_index("ix_entity_name", table_name="entity")
    op.drop_index("ix_entity_kind", table_name="entity")
    op.drop_index("ix_entity_path", table_name="entity")
    op.drop_index("ix_entity_parent_id", table_name="entity")
    op.drop_table("entity")
