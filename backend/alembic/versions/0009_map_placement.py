"""M8+ house-map: blank-canvas floors + furniture footprints.

Makes floor_plan.image_path nullable (a blank-canvas floor is drawn in-app with
no background image) and adds map_placement — an axis-aligned furniture/container
footprint on the top-view floor, in the same fixed canvas coordinate space as
map_region polygons.

image_w/image_h are now the FIXED canvas frame; image swaps no longer rescale
them. Existing floors all carry an image and real dimensions, so the defensive
backfill below is a no-op in practice.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-19

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive: any floor missing canvas dims gets the default 1600x1200 so the
    # coordinate frame always exists (real rows already have image dimensions).
    op.execute("UPDATE floor_plan SET image_w = 1600 WHERE image_w IS NULL")
    op.execute("UPDATE floor_plan SET image_h = 1200 WHERE image_h IS NULL")

    # image_path -> nullable (blank-canvas floors). batch_alter_table recreates
    # the table on SQLite; FK-off default in the alembic env keeps it safe.
    with op.batch_alter_table("floor_plan") as batch_op:
        batch_op.alter_column("image_path", existing_type=sa.Text(), nullable=True)

    op.create_table(
        "map_placement",
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
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("w", sa.Float(), nullable=False),
        sa.Column("h", sa.Float(), nullable=False),
        sa.Column("rotation", sa.Float(), nullable=False, server_default="0"),
        sa.Column("label_x", sa.Float(), nullable=True),
        sa.Column("label_y", sa.Float(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "floor_plan_id", "entity_id", name="uq_map_placement_floor_entity"
        ),
    )
    op.create_index("ix_map_placement_floor_plan_id", "map_placement", ["floor_plan_id"])
    op.create_index("ix_map_placement_entity_id", "map_placement", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_map_placement_entity_id", table_name="map_placement")
    op.drop_index("ix_map_placement_floor_plan_id", table_name="map_placement")
    op.drop_table("map_placement")
    # NOTE: irreversible for blank-canvas floors — NULL image_path rows violate
    # the restored NOT NULL. Backfill a sentinel so downgrade doesn't crash;
    # such rows have no real image and should be deleted by an operator.
    op.execute("UPDATE floor_plan SET image_path = '' WHERE image_path IS NULL")
    with op.batch_alter_table("floor_plan") as batch_op:
        batch_op.alter_column("image_path", existing_type=sa.Text(), nullable=False)
