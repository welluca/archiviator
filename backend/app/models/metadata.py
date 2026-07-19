"""Metadata ORM models (M4): tags, categories, custom field defs/values, presets.

tag.name and category.name are UNIQUE COLLATE NOCASE — duplicate checks in
app.services.metadata compare through the column so they inherit the collation.
The search_fts index shadowing these tables is maintained by SQL triggers
created in migration 0004 (mirrored by app.services.search.rebuild_search).
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

FIELD_TYPES = ("text", "number", "date", "url")


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text(collation="NOCASE"), unique=True)
    color: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Tag {self.id} {self.name!r}>"


class EntityTag(Base):
    """Association rows entity <-> tag; always written via explicit INSERT/DELETE
    statements (never relationship cascades) so the search_fts triggers fire."""

    __tablename__ = "entity_tag"

    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text(collation="NOCASE"), unique=True)
    icon: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<Category {self.id} {self.name!r}>"


class FieldDef(Base):
    """Custom field definition. category_id NULL means global (all categories)."""

    __tablename__ = "field_def"
    __table_args__ = (
        CheckConstraint(
            "type IN ('text','number','date','url')", name="ck_field_def_type"
        ),
        UniqueConstraint("category_id", "name", name="uq_field_def_category_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<FieldDef {self.id} {self.name!r} {self.type}>"


class FieldValue(Base):
    """A typed value for (entity, field_def). value_text is always the canonical
    string; value_num/value_date carry the coerced form for number/date types."""

    __tablename__ = "field_value"
    __table_args__ = (
        UniqueConstraint("entity_id", "field_def_id", name="uq_field_value_entity_def"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), index=True
    )
    field_def_id: Mapped[int] = mapped_column(
        ForeignKey("field_def.id", ondelete="CASCADE"), index=True
    )
    value_text: Mapped[str] = mapped_column(Text)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_date: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<FieldValue {self.id} entity={self.entity_id} def={self.field_def_id}>"


class Preset(Base):
    """Named JSON payload (stored serialized); M4 exposes CRUD only, the apply
    flow arrives with the M7 UI."""

    __tablename__ = "preset"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    payload: Mapped[str] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Preset {self.id} {self.name!r}>"
