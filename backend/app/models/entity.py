"""Entity ORM model: the containment tree (spaces, furniture, containers, items).

Full M2 column set; the UI exposes a subset until later milestones. The
path/depth/breadcrumb columns are denormalized caches maintained exclusively by
app.services.tree — path is a '/id/id/.../' chain including self (e.g. '/1/4/9/').
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.dt import utcnow

if TYPE_CHECKING:
    from app.models.metadata import Tag

KINDS = ("space", "furniture", "container", "item")


class Entity(Base):
    __tablename__ = "entity"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('space','furniture','container','item')", name="ck_entity_kind"
        ),
        Index("ix_entity_draft", "draft", sqlite_where=text("draft = 1")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(Text, index=True)
    subtype: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("entity.id", ondelete="RESTRICT"), index=True
    )
    # Cover photo (an attachment row owned by this entity). use_alter breaks the
    # entity <-> attachment FK cycle at metadata/DDL level; SQLite clears it via
    # ON DELETE SET NULL when the attachment goes away.
    cover_attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "attachment.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_entity_cover_attachment",
        )
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="SET NULL"), index=True
    )
    # Read-only convenience; API responses use the batched _tags_map fetch instead
    # (lazy='noload' so no accidental N+1, viewonly so flush never touches entity_tag —
    # associations are written via explicit statements that fire the FTS triggers).
    tags: Mapped[list["Tag"]] = relationship(
        secondary="entity_tag", lazy="noload", viewonly=True, order_by="Tag.name"
    )

    # Tree caches (see module docstring).
    path: Mapped[str] = mapped_column(Text, default="", index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    breadcrumb: Mapped[str] = mapped_column(Text, default="")

    asset_tag: Mapped[str | None] = mapped_column(Text, unique=True)
    quantity: Mapped[float] = mapped_column(Float, default=1)
    unit: Mapped[str | None] = mapped_column(Text)
    is_consumable: Mapped[bool] = mapped_column(Boolean, default=False)
    low_stock_threshold: Mapped[float | None] = mapped_column(Float)
    purchase_date: Mapped[str | None] = mapped_column(Text)
    purchase_price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    purchase_from: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(Text)
    current_value: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    insured: Mapped[bool] = mapped_column(Boolean, default=False)
    warranty_expires: Mapped[str | None] = mapped_column(Text)
    warranty_lifetime: Mapped[bool] = mapped_column(Boolean, default=False)
    warranty_notes: Mapped[str | None] = mapped_column(Text)
    serial_number: Mapped[str | None] = mapped_column(Text)
    model_number: Mapped[str | None] = mapped_column(Text)
    manufacturer: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    sold_date: Mapped[str | None] = mapped_column(Text)
    sold_to: Mapped[str | None] = mapped_column(Text)
    sold_price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    sold_notes: Mapped[str | None] = mapped_column(Text)
    import_ref: Mapped[str | None] = mapped_column(Text, index=True)
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:
        return f"<Entity {self.id} {self.kind} {self.name!r}>"
