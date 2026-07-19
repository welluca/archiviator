"""Label ORM models (M5): asset-tag sequence, sheet templates, print batches.

Asset tags live on entity.asset_tag (TEXT UNIQUE, created in 0002); these
tables add the monotonically allocated PREFIX-NNNN sequence, the printable
A4 sheet geometry, and the per-sticker lifecycle (unclaimed -> claimed/void).
A tag can exist WITHOUT a printed_label row (auto-assign never prints), and a
claimed label reverts to 'unclaimed' when its entity is deleted — the sticker
is still physically out there and can be re-bound.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.dt import utcnow

LABEL_STATUSES = ("unclaimed", "claimed", "void")


class TagSequence(Base):
    """next_value per tag prefix; allocation is a single atomic
    UPDATE .. RETURNING in app.services.labels.allocate_tags."""

    __tablename__ = "tag_sequence"

    prefix: Mapped[str] = mapped_column(Text, primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    def __repr__(self) -> str:
        return f"<TagSequence {self.prefix!r} next={self.next_value}>"


class LabelTemplate(Base):
    """A4 sticker-sheet geometry (all dimensions in mm, y measured from the top).
    gutter is pitch minus label size, so x = margin_left + col * (label_w + gutter_x)."""

    __tablename__ = "label_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    page_w_mm: Mapped[float] = mapped_column(Float)
    page_h_mm: Mapped[float] = mapped_column(Float)
    cols: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int] = mapped_column(Integer)
    label_w_mm: Mapped[float] = mapped_column(Float)
    label_h_mm: Mapped[float] = mapped_column(Float)
    margin_top_mm: Mapped[float] = mapped_column(Float)
    margin_left_mm: Mapped[float] = mapped_column(Float)
    gutter_x_mm: Mapped[float] = mapped_column(Float)
    gutter_y_mm: Mapped[float] = mapped_column(Float)
    qr_size_mm: Mapped[float] = mapped_column(Float)
    show_name: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    show_breadcrumb: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    def __repr__(self) -> str:
        return f"<LabelTemplate {self.id} {self.name!r}>"


class LabelBatch(Base):
    __tablename__ = "label_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("label_template.id", ondelete="RESTRICT"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def __repr__(self) -> str:
        return f"<LabelBatch {self.id}>"


class PrintedLabel(Base):
    """One physically printed sticker. entity_id/claimed_at are set on claim;
    the FK is SET NULL so a deleted entity leaves the row (the delete hook in
    app.services.labels also reverts status to 'unclaimed')."""

    __tablename__ = "printed_label"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unclaimed','claimed','void')", name="ck_printed_label_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("label_batch.id", ondelete="CASCADE"), index=True
    )
    asset_tag: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, default="unclaimed", server_default="unclaimed")
    entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("entity.id", ondelete="SET NULL"), index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return f"<PrintedLabel {self.id} {self.asset_tag!r} {self.status}>"
