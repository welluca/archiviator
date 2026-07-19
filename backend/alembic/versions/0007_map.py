"""M8 house map: floor_plan, map_region, furniture_grid, grid_cell.

furniture_grid.parent_cell_id (sub-grid anchor) and grid_cell.grid_id form an
FK cycle, so the parent-cell FK is attached afterwards via batch_alter_table —
on SQLite that recreates the (still empty) table, and the alembic env engine
leaves PRAGMA foreign_keys at its OFF default so the recreate cannot trip over
the cycle (same pattern as 0003's entity.cover_attachment_id).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-19

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "floor_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,  # one plan per space
        ),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("image_w", sa.Integer(), nullable=True),
        sa.Column("image_h", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "map_region",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "floor_plan_id",
            sa.Integer(),
            sa.ForeignKey("floor_plan.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("polygon_json", sa.Text(), nullable=False),
        sa.Column("label_x", sa.Float(), nullable=True),
        sa.Column("label_y", sa.Float(), nullable=True),
        sa.UniqueConstraint("floor_plan_id", "entity_id", name="uq_map_region_floor_entity"),
    )
    op.create_index("ix_map_region_floor_plan_id", "map_region", ["floor_plan_id"])
    op.create_index("ix_map_region_entity_id", "map_region", ["entity_id"])

    op.create_table(
        "furniture_grid",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("cols", sa.Integer(), nullable=False),
        sa.Column("parent_cell_id", sa.Integer(), nullable=True),  # FK added below
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "grid_cell",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "grid_id",
            sa.Integer(),
            sa.ForeignKey("furniture_grid.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row", sa.Integer(), nullable=False),
        sa.Column("col", sa.Integer(), nullable=False),
        sa.Column("row_span", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("col_span", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cell_type", sa.Text(), nullable=False, server_default="shelf"),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,  # 1:1 cell-to-container binding
        ),
        sa.CheckConstraint(
            "cell_type IN ('drawer','shelf','door','box','void','other')",
            name="ck_grid_cell_type",
        ),
        sa.UniqueConstraint("grid_id", "row", "col", name="uq_grid_cell_grid_row_col"),
    )
    op.create_index("ix_grid_cell_grid_id", "grid_cell", ["grid_id"])

    with op.batch_alter_table("furniture_grid") as batch_op:
        batch_op.create_foreign_key(
            "fk_furniture_grid_parent_cell",
            "grid_cell",
            ["parent_cell_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_furniture_grid_entity_id", "furniture_grid", ["entity_id"])
    op.create_index("ix_furniture_grid_parent_cell_id", "furniture_grid", ["parent_cell_id"])


def downgrade() -> None:
    op.drop_index("ix_furniture_grid_parent_cell_id", table_name="furniture_grid")
    op.drop_index("ix_furniture_grid_entity_id", table_name="furniture_grid")
    op.drop_index("ix_grid_cell_grid_id", table_name="grid_cell")
    op.drop_table("grid_cell")
    op.drop_table("furniture_grid")
    op.drop_index("ix_map_region_entity_id", table_name="map_region")
    op.drop_index("ix_map_region_floor_plan_id", table_name="map_region")
    op.drop_table("map_region")
    op.drop_table("floor_plan")
