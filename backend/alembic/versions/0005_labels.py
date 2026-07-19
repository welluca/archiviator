"""M5 labels: tag_sequence, label_template, label_batch, printed_label + seeds.

Seeds: tag sequence 'A' starting at 1, and three A4 Avery presets with the
published sheet geometry (gutter = pitch minus label size):
  L7160  63.5 x 38.1, 3 x 7,  margins top 15.1 left 7.2,  pitch x 66.0  y 38.1
  L7651  38.1 x 21.2, 5 x 13, margins top 10.7 left 4.7,  pitch x 40.6  y 21.2
  L7165  99.1 x 67.7, 2 x 4,  margins top 12.9 left 4.65, pitch x 101.6 y 67.7

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tag_sequence",
        sa.Column("prefix", sa.Text(), primary_key=True),
        sa.Column("next_value", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "label_template",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("page_w_mm", sa.Float(), nullable=False),
        sa.Column("page_h_mm", sa.Float(), nullable=False),
        sa.Column("cols", sa.Integer(), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("label_w_mm", sa.Float(), nullable=False),
        sa.Column("label_h_mm", sa.Float(), nullable=False),
        sa.Column("margin_top_mm", sa.Float(), nullable=False),
        sa.Column("margin_left_mm", sa.Float(), nullable=False),
        sa.Column("gutter_x_mm", sa.Float(), nullable=False),
        sa.Column("gutter_y_mm", sa.Float(), nullable=False),
        sa.Column("qr_size_mm", sa.Float(), nullable=False),
        sa.Column("show_name", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("show_breadcrumb", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_table(
        "label_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("label_template.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_label_batch_template_id", "label_batch", ["template_id"])
    op.create_table(
        "printed_label",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("label_batch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_tag", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="unclaimed"),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('unclaimed','claimed','void')", name="ck_printed_label_status"
        ),
    )
    op.create_index("ix_printed_label_batch_id", "printed_label", ["batch_id"])
    op.create_index("ix_printed_label_entity_id", "printed_label", ["entity_id"])

    op.execute("INSERT INTO tag_sequence (prefix, next_value) VALUES ('A', 1)")

    templates = sa.table(
        "label_template",
        sa.column("name", sa.Text),
        sa.column("page_w_mm", sa.Float),
        sa.column("page_h_mm", sa.Float),
        sa.column("cols", sa.Integer),
        sa.column("rows", sa.Integer),
        sa.column("label_w_mm", sa.Float),
        sa.column("label_h_mm", sa.Float),
        sa.column("margin_top_mm", sa.Float),
        sa.column("margin_left_mm", sa.Float),
        sa.column("gutter_x_mm", sa.Float),
        sa.column("gutter_y_mm", sa.Float),
        sa.column("qr_size_mm", sa.Float),
        sa.column("show_name", sa.Boolean),
        sa.column("show_breadcrumb", sa.Boolean),
    )
    common = {"page_w_mm": 210.0, "page_h_mm": 297.0}
    op.bulk_insert(
        templates,
        [
            {
                "name": "Avery L7160 (63.5×38.1, 3×7)",
                **common,
                "cols": 3, "rows": 7,
                "label_w_mm": 63.5, "label_h_mm": 38.1,
                "margin_top_mm": 15.1, "margin_left_mm": 7.2,
                "gutter_x_mm": 2.5, "gutter_y_mm": 0.0,  # pitch 66.0 / 38.1
                "qr_size_mm": 28.0,
                "show_name": True, "show_breadcrumb": True,
            },
            {
                "name": "Avery L7651 (38.1×21.2, 5×13)",
                **common,
                "cols": 5, "rows": 13,
                "label_w_mm": 38.1, "label_h_mm": 21.2,
                "margin_top_mm": 10.7, "margin_left_mm": 4.7,
                "gutter_x_mm": 2.5, "gutter_y_mm": 0.0,  # pitch 40.6 / 21.2
                "qr_size_mm": 16.0,
                "show_name": False, "show_breadcrumb": False,
            },
            {
                "name": "Avery L7165 (99.1×67.7, 2×4)",
                **common,
                "cols": 2, "rows": 4,
                "label_w_mm": 99.1, "label_h_mm": 67.7,
                "margin_top_mm": 12.9, "margin_left_mm": 4.65,
                "gutter_x_mm": 2.5, "gutter_y_mm": 0.0,  # pitch 101.6 / 67.7
                "qr_size_mm": 45.0,
                "show_name": True, "show_breadcrumb": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_printed_label_entity_id", table_name="printed_label")
    op.drop_index("ix_printed_label_batch_id", table_name="printed_label")
    op.drop_table("printed_label")
    op.drop_index("ix_label_batch_template_id", table_name="label_batch")
    op.drop_table("label_batch")
    op.drop_table("label_template")
    op.drop_table("tag_sequence")
