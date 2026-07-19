"""Entity tree service: containment rules and path/depth/breadcrumb cache maintenance.

All tree logic lives here; routers only translate domain errors to HTTP. Every
mutator runs in a single transaction (one commit at the end). Subtree rewrites
use an index-usable range predicate on `path` plus substr arithmetic, so only
the leading prefix of each cached value is replaced — a naive REPLACE() would
corrupt entities whose names repeat in deeper breadcrumb segments.
"""

from sqlalchemy import and_, case, exists, func, literal, select, update
from sqlalchemy.orm import Session, aliased

from app.models.entity import Entity
from app.models.meta import Meta
from app.models.metadata import Category
from app.utils.dt import utcnow


class TreeError(Exception):
    """Base class for tree domain errors; str(exc) becomes the HTTP detail."""


class NotFoundError(TreeError):
    """Entity (or referenced parent) does not exist -> 404."""


class RuleViolation(TreeError):
    """Business-rule violation (containment, cycle, Inbox, children) -> 409."""


# Which child kinds each parent kind may contain.
ALLOWED_CHILDREN: dict[str, set[str]] = {
    "space": {"space", "furniture", "container", "item"},
    "furniture": {"container", "item"},
    "container": {"container", "item"},
    "item": set(),
}

# Inventory columns (M6) patched straight through by update_entity — validation
# lives in the router schema. Also the copy set for metadata.duplicate_entity.
INVENTORY_FIELDS: tuple[str, ...] = (
    "quantity", "unit", "is_consumable", "low_stock_threshold",
    "purchase_date", "purchase_price", "purchase_from", "currency",
    "current_value", "insured", "warranty_expires", "warranty_lifetime",
    "warranty_notes", "serial_number", "model_number", "manufacturer",
    "sold_date", "sold_to", "sold_price", "sold_notes",
)


def not_in_archived_subtree():
    """SQL predicate: entity is NOT inside an archived subtree (itself included).

    An entity is hidden when any prefix of its path is an archived row's path.
    THE single definition of archived visibility — tree listing, search and the
    inventory queries all reuse it so the semantics can never drift.
    """
    ancestor = aliased(Entity)
    hidden = exists(
        select(ancestor.id).where(
            ancestor.archived_at.is_not(None),
            func.substr(Entity.path, 1, func.length(ancestor.path)) == ancestor.path,
        )
    )
    return ~hidden


def subtree_range_filter(path: str):
    """Index-usable range predicate selecting `path`'s node and all descendants.

    `path` is a '/id/id/.../' chain ending in '/'. Every subtree member starts
    with it, and since '0' is the ASCII successor of '/', the half-open range
    [path, path[:-1] || '0') matches exactly the strings prefixed by `path` —
    including rejecting id-prefix traps like '/12/' when path is '/1/'. LIKE
    would skip the index on SQLite's default collation; this range uses it.
    """
    prefix = path[:-1]
    return and_(Entity.path >= path, Entity.path < prefix + "0")


def _get(db: Session, entity_id: int) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError(f"Entity {entity_id} not found")
    return entity


def get_inbox_id(db: Session) -> int | None:
    """Id of the seeded Inbox root, from meta — protection is keyed to this id,
    never to the mutable subtype column (which any PATCH could change)."""
    value = db.scalar(select(Meta.value).where(Meta.key == "inbox_entity_id"))
    return int(value) if value is not None else None


def is_protected(db: Session, entity: Entity) -> bool:
    return entity.id == get_inbox_id(db)


def _guard_protected(db: Session, entity: Entity, action: str) -> None:
    if is_protected(db, entity):
        raise RuleViolation(f"The Inbox cannot be {action}")


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise RuleViolation("Name must not be blank")
    return name


def _check_containment(parent: Entity | None, child_kind: str) -> None:
    if parent is None:
        if child_kind != "space":
            raise RuleViolation(f"Only spaces can be at the root level, not {child_kind}")
    elif child_kind not in ALLOWED_CHILDREN[parent.kind]:
        raise RuleViolation(f"A {parent.kind} cannot contain a {child_kind}")


def _caches_for(parent: Entity | None, entity_id: int, name: str) -> tuple[str, int, str]:
    """Compute (path, depth, breadcrumb) for a node under `parent` (None = root)."""
    if parent is None:
        return f"/{entity_id}/", 0, name
    return f"{parent.path}{entity_id}/", parent.depth + 1, f"{parent.breadcrumb} › {name}"


# --- queries ------------------------------------------------------------------


def get_entity(db: Session, entity_id: int) -> Entity:
    return _get(db, entity_id)


def list_tree(db: Session, include_archived: bool = False) -> list[Entity]:
    """Flat listing ordered by path (parents always before children).

    Archiving hides the WHOLE subtree: a live entity inside an archived box
    would otherwise be returned parentless and silently dropped by the client.
    """
    stmt = select(Entity).order_by(Entity.path)
    if not include_archived:
        stmt = stmt.where(not_in_archived_subtree())
    return list(db.scalars(stmt))


_KIND_ORDER = case(
    (Entity.kind == "space", 0),
    (Entity.kind == "furniture", 1),
    (Entity.kind == "container", 2),
    else_=3,
)


def list_children(db: Session, parent_id: int, include_archived: bool = False) -> list[Entity]:
    """Direct children ordered by kind (space, furniture, container, item) then name —
    the same order the frontend tree panel uses, so the two panels never disagree."""
    _get(db, parent_id)
    stmt = select(Entity).where(Entity.parent_id == parent_id)
    if not include_archived:
        stmt = stmt.where(Entity.archived_at.is_(None))
    stmt = stmt.order_by(_KIND_ORDER, func.lower(Entity.name))
    return list(db.scalars(stmt))


def entity_path(db: Session, entity_id: int) -> list[Entity]:
    """Ancestor chain root-first, including the entity itself."""
    entity = _get(db, entity_id)
    ids = [int(part) for part in entity.path.strip("/").split("/")]
    by_id = {e.id: e for e in db.scalars(select(Entity).where(Entity.id.in_(ids)))}
    return [by_id[i] for i in ids]


def child_counts(db: Session, parent_ids: list[int] | None = None) -> dict[int, int]:
    """Direct-child counts (including archived children) as {parent_id: count}.

    Single grouped query — callers must use this instead of per-row counts.
    Pass None to count for all parents (tree listing).
    """
    stmt = (
        select(Entity.parent_id, func.count(Entity.id))
        .where(Entity.parent_id.is_not(None))
        .group_by(Entity.parent_id)
    )
    if parent_ids is not None:
        if not parent_ids:
            return {}
        stmt = stmt.where(Entity.parent_id.in_(parent_ids))
    return {parent_id: count for parent_id, count in db.execute(stmt)}


# --- mutators (each commits exactly once) -------------------------------------
#
# commit=False is used ONLY by app.services.io_csv (CSV import): rows run under
# per-row SAVEPOINTs and the whole import commits once at the end (or rolls back
# entirely for dry_run). Default behavior is identical to before.


def create_entity(
    db: Session,
    *,
    name: str,
    kind: str,
    parent_id: int | None = None,
    subtype: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    commit: bool = True,
) -> Entity:
    if kind not in ALLOWED_CHILDREN:
        raise RuleViolation(f"Unknown kind {kind!r}")
    name = _clean_name(name)
    parent = _get(db, parent_id) if parent_id is not None else None
    _check_containment(parent, kind)

    entity = Entity(
        name=name,
        kind=kind,
        parent_id=parent_id,
        subtype=subtype,
        description=description,
        notes=notes,
    )
    db.add(entity)
    db.flush()  # assigns entity.id, needed for the path cache
    entity.path, entity.depth, entity.breadcrumb = _caches_for(parent, entity.id, name)
    if commit:
        db.commit()
    return entity


def update_entity(db: Session, entity_id: int, changes: dict, commit: bool = True) -> Entity:
    """Apply a partial update; a name change rewrites the whole subtree's breadcrumbs."""
    entity = _get(db, entity_id)
    for field in ("subtype", "description", "notes", *INVENTORY_FIELDS):
        if field in changes:
            setattr(entity, field, changes[field])
    if "category_id" in changes:
        category_id = changes["category_id"]
        if category_id is not None and db.get(Category, category_id) is None:
            raise NotFoundError(f"Category {category_id} not found")
        entity.category_id = category_id
    new_name = changes.get("name")
    if new_name is not None:
        new_name = _clean_name(new_name)
    if new_name is not None and new_name != entity.name:
        old_breadcrumb = entity.breadcrumb
        parent_prefix = old_breadcrumb[: len(old_breadcrumb) - len(entity.name)]
        entity.name = new_name
        db.flush()
        # Replace only the leading old-breadcrumb prefix on every subtree row
        # (the renamed node itself contributes an empty substr tail).
        db.execute(
            update(Entity)
            .where(subtree_range_filter(entity.path))
            .values(
                breadcrumb=literal(parent_prefix + new_name)
                + func.substr(Entity.breadcrumb, len(old_breadcrumb) + 1),
                updated_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        db.expire_all()
    if commit:
        db.commit()
    return entity


def move_entity(
    db: Session, entity_id: int, new_parent_id: int | None, commit: bool = True
) -> Entity:
    entity = _get(db, entity_id)
    _guard_protected(db, entity, "moved")

    parent: Entity | None = None
    if new_parent_id is not None:
        parent = _get(db, new_parent_id)
        if f"/{entity.id}/" in parent.path:
            raise RuleViolation("Cannot move an entity under itself or its own descendant")
    _check_containment(parent, entity.kind)

    old_path, old_depth, old_breadcrumb = entity.path, entity.depth, entity.breadcrumb
    new_path, new_depth, new_breadcrumb = _caches_for(parent, entity.id, entity.name)

    entity.parent_id = new_parent_id
    db.flush()
    # Rewrite path/depth/breadcrumb for the whole subtree in the same transaction,
    # swapping only the leading old prefix of each cached value.
    db.execute(
        update(Entity)
        .where(subtree_range_filter(old_path))
        .values(
            path=literal(new_path) + func.substr(Entity.path, len(old_path) + 1),
            depth=Entity.depth + (new_depth - old_depth),
            breadcrumb=literal(new_breadcrumb)
            + func.substr(Entity.breadcrumb, len(old_breadcrumb) + 1),
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    db.expire_all()

    # ── Map-view consistency (M8), same transaction. Imports inside the
    # function, like the media/labels hooks in delete_entity, to avoid
    # service-layer cycles. ──────────────────────────────────────────────────
    from app.models.map import FloorPlan, FurnitureGrid, GridCell, MapRegion

    # (a) The MOVED entity's own cell binding: a grid cell renders a direct
    # child of its grid's entity, so once the entity leaves that parent the
    # binding is stale — unbind the cell (the drawer stays; the box moved
    # elsewhere). Any inner layout anchored on that cell BELONGS to the moved
    # container, so detach it (parent_cell_id -> NULL): it survives as a
    # top-level grid, still viewable from the container's own Layout section.
    # Bindings of the moved entity's DESCENDANTS are relative and stay valid.
    cell = db.scalar(select(GridCell).where(GridCell.entity_id == entity.id))
    if cell is not None:
        cell_grid = db.get(FurnitureGrid, cell.grid_id)
        if cell_grid.entity_id != new_parent_id:
            db.execute(
                update(FurnitureGrid)
                .where(FurnitureGrid.parent_cell_id == cell.id)
                .values(parent_cell_id=None)
                .execution_options(synchronize_session=False)
            )
            cell.entity_id = None

    # (b) Regions of the moved subtree: a trace is only meaningful while its
    # room is still a strict descendant of its floor plan's space — delete the
    # ones this move invalidated (the room physically left that floor). Moves
    # WITHIN the floor's subtree keep their regions, and floor plans themselves
    # are unaffected by moves.
    region_rows = db.execute(
        select(MapRegion, Entity.path)
        .join(Entity, Entity.id == MapRegion.entity_id)
        .where(subtree_range_filter(new_path))
    ).all()
    if region_rows:
        floor_paths = {
            floor_id: path
            for floor_id, path in db.execute(
                select(FloorPlan.id, Entity.path)
                .join(Entity, Entity.id == FloorPlan.entity_id)
                .where(FloorPlan.id.in_({r.floor_plan_id for r, _ in region_rows}))
            )
        }
        for region, room_path in region_rows:
            floor_path = floor_paths[region.floor_plan_id]
            # Strict-descendant check, mirroring mapsvc.upsert_region.
            if room_path == floor_path or not room_path.startswith(floor_path):
                db.delete(region)

    if commit:
        db.commit()
    return entity


def archive_entity(db: Session, entity_id: int) -> Entity:
    entity = _get(db, entity_id)
    _guard_protected(db, entity, "archived")
    if entity.archived_at is None:
        entity.archived_at = utcnow().isoformat(sep=" ")
        db.commit()
    return entity


def unarchive_entity(db: Session, entity_id: int) -> Entity:
    entity = _get(db, entity_id)
    if entity.archived_at is not None:
        entity.archived_at = None
        db.commit()
    return entity


def delete_entity(db: Session, entity_id: int) -> None:
    entity = _get(db, entity_id)
    _guard_protected(db, entity, "deleted")
    has_children = db.scalar(
        select(func.count(Entity.id)).where(Entity.parent_id == entity_id)
    )
    if has_children:
        raise RuleViolation("Cannot delete an entity that has children (archive it instead)")
    # The FK cascade removes attachment rows silently — collect their hashes first
    # so the refcounted file cleanup still runs for whatever becomes unreferenced.
    # Same for the entity's floor plan (M8): the row cascades, the image file is
    # refcounted across floor_plan rows. Imports inside the function (like the
    # media hook) to avoid service cycles.
    from app.models.attachment import Attachment
    from app.models.map import FloorPlan
    from app.services import labels as labels_svc
    from app.services import media

    hashes = set(
        db.scalars(
            select(Attachment.content_hash).where(
                Attachment.entity_id == entity_id, Attachment.content_hash.is_not(None)
            )
        )
    )
    floor_images = set(
        db.scalars(select(FloorPlan.image_path).where(FloorPlan.entity_id == entity_id))
    )
    # A claimed printed label reverts to 'unclaimed' in the same transaction —
    # the sticker is still physically out there and can be re-bound.
    labels_svc.release_on_entity_delete(db, entity)
    db.delete(entity)
    db.commit()
    for content_hash in hashes:
        media.delete_files_if_unreferenced(db, content_hash)
    for image_path in floor_images:
        media.delete_floorplan_if_unreferenced(db, image_path)
