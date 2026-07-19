"""CSV import/export service (M6).

Export (our dialect) emits ONE row per entity — every kind including spaces, in
path order — so a full tree round-trips: import re-resolves each row via its
import_ref (stored ref, or the generated 'arch-<id>' fallback for entities that
never had one) and updates instead of duplicating. `?dialect=homebox` emits the
HomeBox HB.* column subset as a migration escape hatch (export only).

Import runs the whole file in ONE transaction: each row executes under a
SAVEPOINT so a failing row rolls back alone (per-row error collection, never
aborting the rest), the non-dry-run path commits once at the end, and dry_run
rolls the entire transaction back after counting would-be creates/updates.
This is why the tree/metadata/labels mutators grew their commit=False mode.

Documented simplifications:
- 'location' is the ' / '-joined parent chain matched case-insensitively level
  by level from the roots; missing intermediate nodes are auto-created as kind
  'space' (auto-created nodes do not count in `created` — that counts CSV rows).
- Unknown category names are created on the fly (same spirit as tags).
- Names containing '/' cannot round-trip through the location column.
"""

import csv
import io
import re

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entity import Entity
from app.models.metadata import Category, EntityTag, FieldDef, FieldValue, Tag
from app.services import labels as labels_svc
from app.services import metadata as metadata_svc
from app.services import tree
from app.services.tree import TreeError


class MalformedCsvError(Exception):
    """Unusable CSV header -> 422 (rows never even start processing)."""


FIELD_PREFIX = "field:"

OUR_COLUMNS = (
    "import_ref", "name", "kind", "subtype", "location", "category", "tags",
    "quantity", "unit", "is_consumable", "low_stock_threshold", "purchase_date",
    "purchase_price", "purchase_from", "currency", "current_value", "insured",
    "warranty_expires", "warranty_lifetime", "warranty_notes", "serial_number",
    "model_number", "manufacturer", "description", "notes", "asset_tag",
)

_FLOAT_COLUMNS = {"quantity", "low_stock_threshold", "purchase_price", "current_value",
                  "sold_price"}
_BOOL_COLUMNS = {"is_consumable", "insured", "warranty_lifetime"}
_DATE_COLUMNS = {"purchase_date", "warranty_expires", "sold_date"}
_TEXT_COLUMNS = {"subtype", "description", "notes", "unit", "purchase_from",
                 "warranty_notes", "serial_number", "model_number", "manufacturer",
                 "sold_to", "sold_notes"}

_GENERATED_REF = re.compile(r"^arch-(\d+)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_LOCATION_SPLIT = re.compile(r"\s*/\s*")


# --- formatting helpers -------------------------------------------------------

# CSV formula-injection guard: spreadsheet apps execute cells starting with one
# of these, so export prefixes them with a literal quote and import strips
# exactly one such quote back off — a symmetric, idempotent round trip.
_FORMULA_CHARS = ("=", "+", "-", "@")


def _guard_formula(cell: str) -> str:
    """Export side of the formula-injection guard."""
    return f"'{cell}" if cell.startswith(_FORMULA_CHARS) else cell


def _unguard_formula(cell: str) -> str:
    """Import side: strip ONE leading ' only when it escapes a formula char."""
    return cell[1:] if cell.startswith("'") and cell[1:2] in _FORMULA_CHARS else cell


def _fmt(value) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else str(value)
    return str(value)


def _location_of(entity: Entity, names: dict[int, str]) -> str:
    """' / '-joined PARENT chain (empty for roots), from the path cache."""
    ancestor_ids = [int(part) for part in entity.path[1:-1].split("/")][:-1]
    return " / ".join(names[a] for a in ancestor_ids)


def _export_ref(entity: Entity) -> str:
    """Stable re-import handle: the stored import_ref, else 'arch-<id>'."""
    return entity.import_ref or f"arch-{entity.id}"


# --- shared export data -------------------------------------------------------


def _defs_in_use(db: Session) -> list[FieldDef]:
    """Field defs with at least one stored value, deduped by name (first by
    sort_order/name wins — import resolves by NAME, so one column per name)."""
    rows = db.scalars(
        select(FieldDef)
        .join(FieldValue, FieldValue.field_def_id == FieldDef.id)
        .group_by(FieldDef.id)
        .order_by(FieldDef.sort_order, FieldDef.name)
    )
    seen: set[str] = set()
    out: list[FieldDef] = []
    for field_def in rows:
        key = field_def.name.lower()
        if key not in seen:
            seen.add(key)
            out.append(field_def)
    return out


def _tag_names_map(db: Session) -> dict[int, list[str]]:
    rows = db.execute(
        select(EntityTag.entity_id, Tag.name)
        .join(Tag, Tag.id == EntityTag.tag_id)
        .order_by(Tag.name)
    )
    out: dict[int, list[str]] = {}
    for entity_id, name in rows:
        out.setdefault(entity_id, []).append(name)
    return out


def _field_values_map(db: Session) -> dict[tuple[int, int], str]:
    """{(entity_id, field_def_id): value_text}."""
    rows = db.execute(
        select(FieldValue.entity_id, FieldValue.field_def_id, FieldValue.value_text)
    )
    return {(entity_id, def_id): text for entity_id, def_id, text in rows}


def _resolve_from(defs: list[FieldDef], category_id: int | None) -> FieldDef | None:
    """Pick a def from same-name candidates: the row's category's def wins,
    then a global def; a def on a DIFFERENT category does not match."""
    if category_id is not None:
        for field_def in defs:
            if field_def.category_id == category_id:
                return field_def
    for field_def in defs:
        if field_def.category_id is None:
            return field_def
    return None


def _resolve_field_def(
    db: Session, name: str, category_id: int | None
) -> FieldDef | None:
    """Def by NAME (case-insensitive) — the per-row import path."""
    defs = list(
        db.scalars(select(FieldDef).where(func.lower(FieldDef.name) == name.lower()))
    )
    return _resolve_from(defs, category_id)


def _defs_by_name(db: Session) -> dict[str, list[FieldDef]]:
    """ALL field defs grouped by lowercased name — prefetched ONCE so the export
    row loop resolves in memory instead of querying per entity per column."""
    out: dict[str, list[FieldDef]] = {}
    for field_def in db.scalars(select(FieldDef)):
        out.setdefault(field_def.name.lower(), []).append(field_def)
    return out


def _entity_field_value(
    entity: Entity,
    field_def: FieldDef,
    values: dict[tuple[int, int], str],
    defs_by_name: dict[str, list[FieldDef]],
) -> str:
    """The value the import would address for this column: resolve the def NAME
    against the entity's category, then look the value up (export symmetry)."""
    resolved = _resolve_from(defs_by_name.get(field_def.name.lower(), []), entity.category_id)
    if resolved is None:
        return ""
    return values.get((entity.id, resolved.id), "")


# --- export -------------------------------------------------------------------


def export_rows(db: Session, dialect: str | None = None):
    """Yield CSV lines (header first). dialect=None -> our dialect;
    'homebox' -> the HB.* subset."""
    entities = list(db.scalars(select(Entity).order_by(Entity.path)))
    names = {e.id: e.name for e in entities}
    tags_map = _tag_names_map(db)
    values = _field_values_map(db)
    field_defs = _defs_in_use(db)
    defs_by_name = _defs_by_name(db)
    categories = {c.id: c.name for c in db.scalars(select(Category))}

    buf = io.StringIO()
    writer = csv.writer(buf)

    def emit(row: list[str]) -> str:
        writer.writerow([_guard_formula(cell) for cell in row])
        line = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        return line

    if dialect == "homebox":
        yield from _export_homebox(
            emit, entities, names, tags_map, values, field_defs, defs_by_name
        )
        return

    yield emit(list(OUR_COLUMNS) + [f"{FIELD_PREFIX}{d.name}" for d in field_defs])
    for e in entities:
        row = [
            _export_ref(e),
            e.name,
            e.kind,
            _fmt(e.subtype),
            _location_of(e, names),
            categories.get(e.category_id, "") if e.category_id else "",
            ";".join(tags_map.get(e.id, [])),
            _fmt(e.quantity),
            _fmt(e.unit),
            _fmt(e.is_consumable),
            _fmt(e.low_stock_threshold),
            _fmt(e.purchase_date),
            _fmt(e.purchase_price),
            _fmt(e.purchase_from),
            _fmt(e.currency),
            _fmt(e.current_value),
            _fmt(e.insured),
            _fmt(e.warranty_expires),
            _fmt(e.warranty_lifetime),
            _fmt(e.warranty_notes),
            _fmt(e.serial_number),
            _fmt(e.model_number),
            _fmt(e.manufacturer),
            _fmt(e.description),
            _fmt(e.notes),
            _fmt(e.asset_tag),
        ]
        row += [_entity_field_value(e, d, values, defs_by_name) for d in field_defs]
        yield emit(row)


def _export_homebox(emit, entities, names, tags_map, values, field_defs, defs_by_name):
    include_asset_id = any(e.asset_tag for e in entities)
    header = ["HB.import_ref", "HB.location", "HB.name", "HB.quantity"]
    if include_asset_id:
        header.append("HB.asset_id")
    header += [
        "HB.archived", "HB.insured", "HB.notes", "HB.purchase_from",
        "HB.purchase_price", "HB.purchase_date", "HB.manufacturer",
        "HB.model_number", "HB.serial_number", "HB.lifetime_warranty",
        "HB.warranty_expires", "HB.warranty_details", "HB.tags",
    ]
    header += [f"HB.field.{d.name}" for d in field_defs]
    yield emit(header)
    for e in entities:
        row = [_export_ref(e), _location_of(e, names), e.name, _fmt(e.quantity)]
        if include_asset_id:
            row.append(_fmt(e.asset_tag))
        row += [
            _fmt(e.archived_at is not None),
            _fmt(e.insured),
            _fmt(e.notes),
            _fmt(e.purchase_from),
            _fmt(e.purchase_price),
            _fmt(e.purchase_date),
            _fmt(e.manufacturer),
            _fmt(e.model_number),
            _fmt(e.serial_number),
            _fmt(e.warranty_lifetime),
            _fmt(e.warranty_expires),
            _fmt(e.warranty_notes),
            ";".join(tags_map.get(e.id, [])),
        ]
        row += [_entity_field_value(e, d, values, defs_by_name) for d in field_defs]
        yield emit(row)


# --- import: cell parsing -----------------------------------------------------


def _parse_float(column: str, raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{column}: {raw!r} is not a number")
    if value < 0:
        raise ValueError(f"{column} must be >= 0")
    return value


def _parse_bool(column: str, raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ValueError(f"{column}: {raw!r} is not a boolean (true/false)")


def _parse_date(column: str, raw: str) -> str:
    from datetime import date

    if not _DATE_RE.match(raw):
        raise ValueError(f"{column}: {raw!r} is not an ISO date (YYYY-MM-DD)")
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{column}: {raw!r} is not a valid date")
    return raw


# --- import: row processing ---------------------------------------------------


def _resolve_location(db: Session, location: str) -> int | None:
    """Walk the ' / '-joined chain from the roots, matching children
    case-insensitively; missing nodes are auto-created as spaces."""
    segments = [s for s in _LOCATION_SPLIT.split(location.strip()) if s]
    parent: Entity | None = None
    for segment in segments:
        parent_clause = (
            Entity.parent_id.is_(None) if parent is None else Entity.parent_id == parent.id
        )
        child = db.scalars(
            select(Entity)
            .where(parent_clause, func.lower(Entity.name) == segment.lower())
            .order_by(Entity.id)
        ).first()
        if child is None:
            child = tree.create_entity(
                db,
                name=segment,
                kind="space",
                parent_id=parent.id if parent is not None else None,
                commit=False,
            )
        parent = child
    return parent.id if parent is not None else None


def _resolve_category(db: Session, raw: str) -> int | None:
    name = raw.strip()
    if not name:
        return None
    # category.name is COLLATE NOCASE; unknown names are created on the fly.
    category = db.scalars(select(Category).where(Category.name == name)).first()
    if category is None:
        category = Category(name=name)
        db.add(category)
        db.flush()
    return category.id


def _entity_changes(cells: dict[str, str]) -> dict:
    """{attr: value} for the plain entity columns present in the CSV. Empty
    cells clear nullable columns and are SKIPPED for NOT NULL ones."""
    changes: dict = {}
    if "name" in cells:
        changes["name"] = cells["name"].strip()  # blank -> RuleViolation later
    for column in _TEXT_COLUMNS:
        if column in cells:
            changes[column] = cells[column].strip() or None
    for column in _FLOAT_COLUMNS:
        if column in cells:
            raw = cells[column].strip()
            if raw:
                changes[column] = _parse_float(column, raw)
            elif column != "quantity":  # quantity is NOT NULL — empty keeps it
                changes[column] = None
    for column in _BOOL_COLUMNS:
        if column in cells:
            raw = cells[column].strip()
            if raw:  # NOT NULL columns — empty keeps the current value
                changes[column] = _parse_bool(column, raw)
    for column in _DATE_COLUMNS:
        if column in cells:
            raw = cells[column].strip()
            changes[column] = _parse_date(column, raw) if raw else None
    if "currency" in cells:
        raw = cells["currency"].strip()
        if raw and not _CURRENCY_RE.match(raw):
            raise ValueError(
                f"currency: {raw!r} is not a 3-letter uppercase code (e.g. EUR)"
            )
        changes["currency"] = raw or None
    return changes


def _apply_fields(db: Session, entity: Entity, field_cells: dict[str, str]) -> None:
    """Upsert field values by def NAME; empty cell removes the stored value.
    An unknown field name errors only when the row actually carries a value."""
    for name, raw in field_cells.items():
        raw = raw.strip()
        field_def = _resolve_field_def(db, name, entity.category_id)
        if field_def is None:
            if not raw:
                continue
            raise ValueError(
                f"Unknown field {name!r} (no global def and none on the row's category)"
            )
        existing = db.scalars(
            select(FieldValue).where(
                FieldValue.entity_id == entity.id,
                FieldValue.field_def_id == field_def.id,
            )
        ).first()
        if not raw:
            if existing is not None:
                # Explicit DELETE (matches metadata service style) so the
                # field_value AD trigger resyncs search_fts.
                db.execute(
                    delete(FieldValue)
                    .where(FieldValue.id == existing.id)
                    .execution_options(synchronize_session=False)
                )
            continue
        value_text, value_num, value_date = metadata_svc._coerce(field_def, raw)
        if existing is not None:
            existing.value_text = value_text
            existing.value_num = value_num
            existing.value_date = value_date
        else:
            db.add(
                FieldValue(
                    entity_id=entity.id,
                    field_def_id=field_def.id,
                    value_text=value_text,
                    value_num=value_num,
                    value_date=value_date,
                )
            )


def _process_row(
    db: Session, cells: dict[str, str], field_cells: dict[str, str]
) -> bool:
    """Create or update one entity from a CSV row; returns True when created."""
    ref = cells.get("import_ref", "").strip() or None
    entity: Entity | None = None
    if ref is not None:
        entity = db.scalars(
            select(Entity).where(Entity.import_ref == ref).order_by(Entity.id)
        ).first()
        if entity is None:
            generated = _GENERATED_REF.match(ref)
            if generated:  # export writes 'arch-<id>' for entities without a ref
                try:
                    candidate = db.get(Entity, int(generated.group(1)))
                except OverflowError:  # id too large for SQLite's 64-bit binding
                    raise ValueError(f"import_ref {ref!r}: id out of range")
                if candidate is not None:
                    # The fallback may claim only ref-LESS entities: an entity
                    # holding a different stored ref is a different row's
                    # identity (never overwrite), and the protected Inbox must
                    # never be addressable this way.
                    if candidate.import_ref is not None:
                        raise ValueError(
                            f"import_ref {ref!r} conflicts with existing ref "
                            f"{candidate.import_ref!r}"
                        )
                    if tree.is_protected(db, candidate):
                        raise ValueError(
                            f"import_ref {ref!r} resolves to the protected Inbox"
                        )
                    entity = candidate

    created = entity is None
    changes = _entity_changes(cells)
    if "category" in cells:
        changes["category_id"] = _resolve_category(db, cells["category"])

    if created:
        name = changes.pop("name", "")
        kind = cells.get("kind", "").strip().lower() or "item"
        parent_id = _resolve_location(db, cells.get("location", ""))
        entity = tree.create_entity(
            db, name=name, kind=kind, parent_id=parent_id, commit=False
        )
        if changes:
            tree.update_entity(db, entity.id, changes, commit=False)
    else:
        kind = cells.get("kind", "").strip().lower()
        if kind and kind != entity.kind:  # empty cell = no change
            raise ValueError(f"kind change from {entity.kind} to {kind} is not supported")
        tree.update_entity(db, entity.id, changes, commit=False)
        if "location" in cells:
            parent_id = _resolve_location(db, cells["location"])
            if parent_id != entity.parent_id:
                tree.move_entity(db, entity.id, parent_id, commit=False)

    if ref is not None and entity.import_ref != ref:
        entity.import_ref = ref

    if "tags" in cells:
        names = [t for t in cells["tags"].split(";") if t.strip()]
        metadata_svc.set_entity_tags(db, entity.id, names, commit=False)

    if field_cells:
        _apply_fields(db, entity, field_cells)

    asset_tag = cells.get("asset_tag", "").strip()
    if asset_tag:  # empty cell = no change (never clears via CSV)
        labels_svc.assign_asset_tag(db, entity.id, tag=asset_tag, commit=False)

    return created


# --- import: driver -----------------------------------------------------------


def _parse_header(text: str) -> tuple[list[str], "csv.reader"]:
    reader = csv.reader(io.StringIO(text))
    try:
        raw_header = next(reader)
    except StopIteration:
        raise MalformedCsvError("CSV is empty")
    header = [h.lstrip("﻿").strip() for h in raw_header]
    if len(header) != len(set(header)):
        raise MalformedCsvError("Duplicate column names in header")
    if "name" not in header:
        raise MalformedCsvError("Missing required column 'name'")
    for column in header:
        if column in OUR_COLUMNS:
            continue
        if column.startswith(FIELD_PREFIX) and column[len(FIELD_PREFIX):].strip():
            continue
        raise MalformedCsvError(f"Unknown column {column!r}")
    return header, reader


def import_csv(db: Session, text: str, dry_run: bool = False) -> dict:
    """Import our-dialect CSV. One transaction: per-row SAVEPOINTs collect
    errors without aborting the rest; dry_run rolls everything back at the end
    (accurate would-be counts, zero writes); otherwise ONE commit at the end.
    Row numbers in errors are 1-based DATA rows (header not counted)."""
    header, reader = _parse_header(text)

    created = 0
    updated = 0
    errors: list[dict] = []
    for row_no, raw in enumerate(reader, start=1):
        if not any(cell.strip() for cell in raw):
            continue  # blank line
        padded = list(raw) + [""] * (len(header) - len(raw))
        # Undo the export-side formula-injection guard on every cell.
        cells = {column: _unguard_formula(value) for column, value in zip(header, padded)}
        field_cells = {
            column[len(FIELD_PREFIX):].strip(): value
            for column, value in cells.items()
            if column.startswith(FIELD_PREFIX)
        }
        savepoint = db.begin_nested()
        try:
            was_created = _process_row(db, cells, field_cells)
            db.flush()  # surface UNIQUE collisions etc. inside the savepoint
            savepoint.commit()
        except (TreeError, ValueError, IntegrityError) as exc:
            savepoint.rollback()
            message = (
                "Conflicts with another row (unique constraint)"
                if isinstance(exc, IntegrityError)
                else str(exc)
            )
            errors.append({"row": row_no, "message": message})
        else:
            if was_created:
                created += 1
            else:
                updated += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return {"created": created, "updated": updated, "errors": errors, "dry_run": dry_run}
