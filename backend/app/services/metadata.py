"""Metadata service: tags, categories, custom fields, presets, entity duplication.

Domain errors reuse tree.NotFoundError / tree.RuleViolation (404 / 409);
InvalidValueError below maps to 422 (typed field-value coercion failures).
Associations (entity_tag) and field values are always written via explicit
INSERT/DELETE statements — never FK-cascade side effects or relationship
cascades — so the search_fts triggers fire deterministically.
"""

import math
import re
from datetime import date

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.models.entity import Entity
from app.models.metadata import Category, EntityTag, FieldDef, FieldValue, Preset, Tag
from app.services import tree
from app.services.tree import NotFoundError, RuleViolation, TreeError


class InvalidValueError(TreeError):
    """Typed field value failed coercion -> 422."""


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_name(name: str, what: str) -> str:
    name = name.strip()
    if not name:
        raise RuleViolation(f"{what} name must not be blank")
    return name


def _clean_tag_name(name: str) -> str:
    name = _clean_name(name, "Tag")
    # The search endpoint takes tags as CSV (?tags=a,b), so a tag name holding
    # a comma could never be filtered on — reject it on every (re)name path.
    if "," in name:
        raise RuleViolation("Tag names cannot contain commas")
    return name


def _get_entity(db: Session, entity_id: int) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError(f"Entity {entity_id} not found")
    return entity


def _get_tag(db: Session, tag_id: int) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise NotFoundError(f"Tag {tag_id} not found")
    return tag


def _get_category(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise NotFoundError(f"Category {category_id} not found")
    return category


def _get_field_def(db: Session, field_def_id: int) -> FieldDef:
    field_def = db.get(FieldDef, field_def_id)
    if field_def is None:
        raise NotFoundError(f"Field def {field_def_id} not found")
    return field_def


def _get_preset(db: Session, preset_id: int) -> Preset:
    preset = db.get(Preset, preset_id)
    if preset is None:
        raise NotFoundError(f"Preset {preset_id} not found")
    return preset


def _tag_by_name(db: Session, name: str) -> Tag | None:
    # tag.name is COLLATE NOCASE, so this comparison is case-insensitive.
    return db.scalars(select(Tag).where(Tag.name == name)).first()


# --- tags ---------------------------------------------------------------------


def list_tags(db: Session) -> list[tuple[Tag, int]]:
    """(tag, usage_count) pairs, name-ordered (NOCASE via the column collation)."""
    stmt = (
        select(Tag, func.count(EntityTag.entity_id))
        .outerjoin(EntityTag, EntityTag.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
    )
    return [(tag, count) for tag, count in db.execute(stmt)]


def tag_usage_count(db: Session, tag_id: int) -> int:
    """Number of entities carrying the tag — one filtered COUNT, no full scan."""
    return db.scalar(
        select(func.count()).select_from(EntityTag).where(EntityTag.tag_id == tag_id)
    )


def create_tag(db: Session, name: str, color: str | None = None) -> Tag:
    name = _clean_tag_name(name)
    if _tag_by_name(db, name) is not None:
        raise RuleViolation(f"Tag {name!r} already exists")
    tag = Tag(name=name, color=color)
    db.add(tag)
    db.commit()
    return tag


def update_tag(db: Session, tag_id: int, changes: dict) -> Tag:
    tag = _get_tag(db, tag_id)
    if "color" in changes:
        tag.color = changes["color"]
    new_name = changes.get("name")
    if new_name is not None:
        new_name = _clean_tag_name(new_name)
        existing = _tag_by_name(db, new_name)
        if existing is not None and existing.id != tag.id:
            raise RuleViolation(f"Tag {new_name!r} already exists")
        tag.name = new_name  # the tag AU trigger resyncs search_fts.tags
    db.commit()
    return tag


def delete_tag(db: Session, tag_id: int) -> None:
    tag = _get_tag(db, tag_id)
    # Explicit association delete (not the FK cascade) so the entity_tag AD
    # trigger deterministically recomputes each entity's search_fts tags column.
    db.execute(
        delete(EntityTag)
        .where(EntityTag.tag_id == tag_id)
        .execution_options(synchronize_session=False)
    )
    db.delete(tag)
    db.commit()


def set_entity_tags(db: Session, entity_id: int, names: list[str]) -> Entity:
    """Replace the entity's full tag set; unknown names are created on the fly
    (create-on-type), duplicates within the payload dedup case-insensitively."""
    entity = _get_entity(db, entity_id)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = raw.strip()
        if not name or name.lower() in seen:
            continue
        if "," in name:  # same CSV-filter rule as _clean_tag_name (create-on-type)
            raise RuleViolation("Tag names cannot contain commas")
        seen.add(name.lower())
        cleaned.append(name)

    tag_ids: list[int] = []
    for name in cleaned:
        tag = _tag_by_name(db, name)
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        tag_ids.append(tag.id)

    db.execute(
        delete(EntityTag)
        .where(EntityTag.entity_id == entity_id)
        .execution_options(synchronize_session=False)
    )
    for tag_id in tag_ids:
        db.add(EntityTag(entity_id=entity_id, tag_id=tag_id))
    db.commit()
    return entity


# --- categories ---------------------------------------------------------------


def list_categories(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.sort_order, Category.name)))


def category_fields_map(db: Session) -> dict[int, list[FieldDef]]:
    """{category_id: [field_defs]} for all non-global defs — ONE query, no N+1."""
    rows = db.scalars(
        select(FieldDef)
        .where(FieldDef.category_id.is_not(None))
        .order_by(FieldDef.sort_order, FieldDef.name)
    )
    out: dict[int, list[FieldDef]] = {}
    for field_def in rows:
        out.setdefault(field_def.category_id, []).append(field_def)
    return out


def _category_by_name(db: Session, name: str) -> Category | None:
    # category.name is COLLATE NOCASE, so this comparison is case-insensitive.
    return db.scalars(select(Category).where(Category.name == name)).first()


def create_category(
    db: Session, name: str, icon: str | None = None, sort_order: int = 0
) -> Category:
    name = _clean_name(name, "Category")
    if _category_by_name(db, name) is not None:
        raise RuleViolation(f"Category {name!r} already exists")
    category = Category(name=name, icon=icon, sort_order=sort_order)
    db.add(category)
    db.commit()
    return category


def update_category(db: Session, category_id: int, changes: dict) -> Category:
    category = _get_category(db, category_id)
    for field in ("icon", "sort_order"):
        if field in changes:
            setattr(category, field, changes[field])
    new_name = changes.get("name")
    if new_name is not None:
        new_name = _clean_name(new_name, "Category")
        existing = _category_by_name(db, new_name)
        if existing is not None and existing.id != category.id:
            raise RuleViolation(f"Category {new_name!r} already exists")
        category.name = new_name
    db.commit()
    return category


def delete_category(db: Session, category_id: int) -> None:
    """Delete a category with its field defs and their values; entities keep
    existing but their category_id clears (FK ON DELETE SET NULL)."""
    category = _get_category(db, category_id)
    def_ids = list(
        db.scalars(select(FieldDef.id).where(FieldDef.category_id == category_id))
    )
    if def_ids:
        # Explicit deletes (not FK cascades) so field_value AD triggers resync fts.
        db.execute(
            delete(FieldValue)
            .where(FieldValue.field_def_id.in_(def_ids))
            .execution_options(synchronize_session=False)
        )
        db.execute(
            delete(FieldDef)
            .where(FieldDef.id.in_(def_ids))
            .execution_options(synchronize_session=False)
        )
    db.delete(category)
    db.commit()


# --- field defs ---------------------------------------------------------------


def _guard_duplicate_def(
    db: Session, category_id: int | None, name: str, exclude_id: int | None = None
) -> None:
    scope = (
        FieldDef.category_id.is_(None)
        if category_id is None
        else FieldDef.category_id == category_id
    )
    existing = db.scalars(select(FieldDef).where(scope, FieldDef.name == name)).first()
    if existing is not None and existing.id != exclude_id:
        raise RuleViolation(f"Field {name!r} already exists for this category")


def create_field_def(
    db: Session,
    *,
    category_id: int | None,
    name: str,
    type: str,
    unit: str | None = None,
    required: bool = False,
    sort_order: int = 0,
) -> FieldDef:
    name = _clean_name(name, "Field")
    if category_id is not None:
        _get_category(db, category_id)
    _guard_duplicate_def(db, category_id, name)
    field_def = FieldDef(
        category_id=category_id,
        name=name,
        type=type,
        unit=unit,
        required=required,
        sort_order=sort_order,
    )
    db.add(field_def)
    db.commit()
    return field_def


def _is_iso_date(value: str) -> bool:
    if not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _recoerce_field_values(db: Session, field_def: FieldDef) -> None:
    """Recompute value_num/value_date for every stored row after a type change.
    Uncoercible values keep their value_text and NULL the typed column; the fts
    fields column indexes value_text only, so no resync is needed."""
    for value in db.scalars(
        select(FieldValue).where(FieldValue.field_def_id == field_def.id)
    ):
        num = None
        if field_def.type == "number":
            try:
                num = float(value.value_text)
            except ValueError:
                num = None
            else:
                if not math.isfinite(num):
                    num = None
        value.value_num = num
        value.value_date = (
            value.value_text
            if field_def.type == "date" and _is_iso_date(value.value_text)
            else None
        )


def update_field_def(db: Session, field_def_id: int, changes: dict) -> FieldDef:
    """Partial update. A type change re-coerces all stored values' value_num/
    value_date in the same transaction (value_text is untouched); a name change
    resyncs search_fts via the field_def AU trigger."""
    field_def = _get_field_def(db, field_def_id)
    type_changed = "type" in changes and changes["type"] != field_def.type
    for field in ("type", "unit", "required", "sort_order"):
        if field in changes:
            setattr(field_def, field, changes[field])
    new_name = changes.get("name")
    if new_name is not None:
        new_name = _clean_name(new_name, "Field")
        _guard_duplicate_def(db, field_def.category_id, new_name, exclude_id=field_def.id)
        field_def.name = new_name
    if type_changed:
        _recoerce_field_values(db, field_def)
    db.commit()
    return field_def


def delete_field_def(db: Session, field_def_id: int) -> None:
    field_def = _get_field_def(db, field_def_id)
    # Explicit value delete (not the FK cascade) so the fts fields column resyncs.
    db.execute(
        delete(FieldValue)
        .where(FieldValue.field_def_id == field_def_id)
        .execution_options(synchronize_session=False)
    )
    db.delete(field_def)
    db.commit()


def list_field_defs(
    db: Session, category_id: int | None = None, include_global: bool = True
) -> list[FieldDef]:
    """Defs applicable to a category (its own + globals); all defs when no
    category is given. include_global=False excludes the globals either way."""
    stmt = select(FieldDef)
    if category_id is not None:
        _get_category(db, category_id)
        own = FieldDef.category_id == category_id
        stmt = stmt.where(
            or_(own, FieldDef.category_id.is_(None)) if include_global else own
        )
    elif not include_global:
        stmt = stmt.where(FieldDef.category_id.is_not(None))
    return list(db.scalars(stmt.order_by(FieldDef.sort_order, FieldDef.name)))


# --- field values -------------------------------------------------------------


def _coerce(field_def: FieldDef, value: str) -> tuple[str, float | None, str | None]:
    """(value_text, value_num, value_date) for a raw string per the def's type.
    value_text is always the canonical string form."""
    if field_def.type == "number":
        try:
            num = float(value)
        except ValueError:
            num = math.nan
        if not math.isfinite(num):
            raise InvalidValueError(f"Field {field_def.name!r} expects a number, got {value!r}")
        text = str(int(num)) if num.is_integer() and abs(num) < 1e15 else str(num)
        return text, num, None
    if field_def.type == "date":
        if not _DATE_RE.match(value):
            raise InvalidValueError(
                f"Field {field_def.name!r} expects an ISO date (YYYY-MM-DD), got {value!r}"
            )
        try:
            date.fromisoformat(value)
        except ValueError:
            raise InvalidValueError(f"Field {field_def.name!r}: {value!r} is not a valid date")
        return value, None, value
    if field_def.type == "url":
        if not value.startswith(("http://", "https://")):
            raise InvalidValueError(
                f"Field {field_def.name!r} expects an http(s):// URL, got {value!r}"
            )
        return value, None, None
    return value, None, None


def get_entity_fields(db: Session, entity_id: int) -> list[tuple[FieldDef, FieldValue]]:
    _get_entity(db, entity_id)
    stmt = (
        select(FieldDef, FieldValue)
        .join(FieldValue, FieldValue.field_def_id == FieldDef.id)
        .where(FieldValue.entity_id == entity_id)
        .order_by(FieldDef.sort_order, FieldDef.name)
    )
    return [(field_def, value) for field_def, value in db.execute(stmt)]


def set_entity_fields(db: Session, entity_id: int, values: list[dict]) -> None:
    """Replace the entity's full field-value set with per-type coercion; an
    empty-string value removes the entry (last payload entry per def wins)."""
    _get_entity(db, entity_id)
    by_def: dict[int, str] = {item["field_def_id"]: item["value"] for item in values}
    rows: list[FieldValue] = []
    for field_def_id, raw in by_def.items():
        field_def = _get_field_def(db, field_def_id)
        raw = raw.strip()
        if not raw:
            continue  # empty string removes the entry
        value_text, value_num, value_date = _coerce(field_def, raw)
        rows.append(
            FieldValue(
                entity_id=entity_id,
                field_def_id=field_def_id,
                value_text=value_text,
                value_num=value_num,
                value_date=value_date,
            )
        )
    db.execute(
        delete(FieldValue)
        .where(FieldValue.entity_id == entity_id)
        .execution_options(synchronize_session=False)
    )
    for row in rows:
        db.add(row)
    db.commit()


def autocomplete_values(
    db: Session, field_def_id: int, q: str = "", limit: int = 20
) -> list[str]:
    """Distinct stored values for a def, most frequent first (fast-entry helper)."""
    _get_field_def(db, field_def_id)
    stmt = (
        select(FieldValue.value_text)
        .where(FieldValue.field_def_id == field_def_id)
        .group_by(FieldValue.value_text)
        .order_by(func.count().desc(), FieldValue.value_text)
        .limit(limit)
    )
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(FieldValue.value_text.ilike(f"{escaped}%", escape="\\"))
    return list(db.scalars(stmt))


# --- duplication --------------------------------------------------------------

_COPY_COLUMNS = (
    "quantity", "unit", "is_consumable", "low_stock_threshold",
    "purchase_date", "purchase_price", "purchase_from", "currency",
    "current_value", "insured", "warranty_expires", "warranty_lifetime",
    "warranty_notes", "serial_number", "model_number", "manufacturer",
    "sold_date", "sold_to", "sold_price", "sold_notes",
)


def duplicate_entity(db: Session, entity_id: int) -> Entity:
    """Copy an entity in place: name + ' (copy)', same parent, all descriptive/
    inventory columns, category, tags and field values. NOT copied: asset_tag
    (unique), attachments, children, draft/archived state."""
    source = _get_entity(db, entity_id)
    if tree.is_protected(db, source):
        raise RuleViolation("The Inbox cannot be duplicated")

    # tree.create_entity keeps the path/depth/breadcrumb caches correct (and
    # commits); the remaining copies land in a second commit right after.
    copy = tree.create_entity(
        db,
        name=f"{source.name} (copy)",
        kind=source.kind,
        parent_id=source.parent_id,
        subtype=source.subtype,
        description=source.description,
        notes=source.notes,
    )
    try:
        for column in _COPY_COLUMNS:
            setattr(copy, column, getattr(source, column))
        copy.category_id = source.category_id
        for tag_id in db.scalars(
            select(EntityTag.tag_id).where(EntityTag.entity_id == source.id)
        ):
            db.add(EntityTag(entity_id=copy.id, tag_id=tag_id))
        for value in db.scalars(
            select(FieldValue).where(FieldValue.entity_id == source.id)
        ):
            db.add(
                FieldValue(
                    entity_id=copy.id,
                    field_def_id=value.field_def_id,
                    value_text=value.value_text,
                    value_num=value.value_num,
                    value_date=value.value_date,
                )
            )
        db.commit()
    except Exception:
        # Compensating cleanup, NOT a savepoint: tree.create_entity has already
        # committed the bare copy, so a rollback cannot undo it. Best-effort
        # delete the half-created entity, then surface the original failure.
        db.rollback()
        try:
            leftover = db.get(Entity, copy.id)
            if leftover is not None:
                db.delete(leftover)
                db.commit()
        except Exception:
            db.rollback()  # cleanup failed — the original error still wins
        raise
    return copy


# --- presets ------------------------------------------------------------------


def list_presets(db: Session) -> list[Preset]:
    return list(db.scalars(select(Preset).order_by(Preset.name)))


def create_preset(db: Session, name: str, payload: str) -> Preset:
    name = _clean_name(name, "Preset")
    if db.scalars(select(Preset).where(Preset.name == name)).first() is not None:
        raise RuleViolation(f"Preset {name!r} already exists")
    preset = Preset(name=name, payload=payload)
    db.add(preset)
    db.commit()
    return preset


def update_preset(db: Session, preset_id: int, changes: dict) -> Preset:
    preset = _get_preset(db, preset_id)
    if "payload" in changes:
        preset.payload = changes["payload"]
    new_name = changes.get("name")
    if new_name is not None:
        new_name = _clean_name(new_name, "Preset")
        existing = db.scalars(select(Preset).where(Preset.name == new_name)).first()
        if existing is not None and existing.id != preset.id:
            raise RuleViolation(f"Preset {new_name!r} already exists")
        preset.name = new_name
    db.commit()
    return preset


def delete_preset(db: Session, preset_id: int) -> None:
    preset = _get_preset(db, preset_id)
    db.delete(preset)
    db.commit()
