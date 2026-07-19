"""House-map service (M8): floor plans, room regions, furniture grids, cell binds.

The map is a VIEW LAYER over the entity tree — every row binds to an entity id
and deleting map rows never deletes entities. Invariants enforced here (409):

- a floor plan sits on a 'space' entity, one plan per entity;
- a region traces a 'space' that is a strict DESCENDANT of the floor's space,
  with a >=3-point polygon inside the image bounds (small tolerance);
- a grid sits on a 'furniture' or 'container' entity; a sub-grid renders its
  parent cell's BOUND entity (the cell must be bound first);
- a cell binds a direct-child container of the grid's entity, each container
  to at most one cell (UNIQUE; IntegrityError mapped to 409);
- non-void cell spans stay in bounds and never overlap other non-void cells.
  'void' cells are holes a neighbour's span may grow over — that is THE way to
  build spanning cells, since creation fills every position with an anchor;
- rebinding/unbinding a cell that anchors a sub-grid is refused (the sub-grid
  would silently stop matching its cell's entity).

Domain errors reuse tree.NotFoundError / tree.RuleViolation (404/409) plus the
media errors (413/415); routers translate. Every mutator commits exactly once.
"""

import json
import math

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entity import Entity
from app.models.map import CELL_TYPES, FloorPlan, FurnitureGrid, GridCell, MapRegion
from app.services import media, tree
from app.services.tree import NotFoundError, RuleViolation

POLYGON_TOLERANCE = 5.0  # px of slack around the image edges for region vertices
GRID_MAX = 12


def _get_entity(db: Session, entity_id: int) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError(f"Entity {entity_id} not found")
    return entity


def _get_floor(db: Session, floor_id: int) -> FloorPlan:
    plan = db.get(FloorPlan, floor_id)
    if plan is None:
        raise NotFoundError(f"Floor plan {floor_id} not found")
    return plan


def _get_grid(db: Session, grid_id: int) -> FurnitureGrid:
    grid = db.get(FurnitureGrid, grid_id)
    if grid is None:
        raise NotFoundError(f"Grid {grid_id} not found")
    return grid


def _get_cell(db: Session, cell_id: int) -> GridCell:
    cell = db.get(GridCell, cell_id)
    if cell is None:
        raise NotFoundError(f"Cell {cell_id} not found")
    return cell


def item_counts(
    db: Session, entities: list[Entity], *, include_archived: bool = False
) -> dict[int, int]:
    """'item' descendant counts as {entity_id: count}.

    ONE query (union of per-entity subtree range predicates) plus a python
    prefix pass — regions/cells per screen number in the dozens at home scale,
    and the pass also handles nested entities counting the same item twice.

    include_archived=True is for grid-cell pills: a physical drawer still holds
    the archived box, so its count keeps every item. Floor-region pills keep the
    default (archived-excluded), matching the rest of the inventory views.
    """
    if not entities:
        return {}
    filters = [
        Entity.kind == "item",
        or_(*(tree.subtree_range_filter(e.path) for e in entities)),
    ]
    if not include_archived:
        filters.append(tree.not_in_archived_subtree())
    paths = list(db.scalars(select(Entity.path).where(*filters)))
    return {e.id: sum(1 for p in paths if p.startswith(e.path)) for e in entities}


# --- floors -------------------------------------------------------------------


def _process_floorplan_upload(data: bytes) -> media.ProcessedFloorplan:
    """Size gate + pipeline; 413/415 happen HERE, before any row is touched.
    MAX_UPLOAD is read at call time so tests can patch it."""
    if len(data) > media.MAX_UPLOAD:
        raise media.FileTooLargeError(
            f"Upload exceeds the {media.MAX_UPLOAD // (1024 * 1024)} MB limit"
        )
    return media.process_floorplan(data)


def list_floors(db: Session) -> list[FloorPlan]:
    stmt = select(FloorPlan).order_by(FloorPlan.sort_order, FloorPlan.id)
    return list(db.scalars(stmt))


def region_counts(db: Session, floor_ids: list[int]) -> dict[int, int]:
    """{floor_plan_id: region count} — single grouped query."""
    if not floor_ids:
        return {}
    rows = db.execute(
        select(MapRegion.floor_plan_id, func.count(MapRegion.id))
        .where(MapRegion.floor_plan_id.in_(floor_ids))
        .group_by(MapRegion.floor_plan_id)
    )
    return {floor_id: count for floor_id, count in rows}


def get_floor(db: Session, floor_id: int) -> FloorPlan:
    return _get_floor(db, floor_id)


def create_floor(db: Session, entity_id: int, data: bytes) -> FloorPlan:
    entity = _get_entity(db, entity_id)
    if entity.kind != "space":
        raise RuleViolation(f"A floor plan must be attached to a space, not a {entity.kind}")
    if db.scalar(select(func.count(FloorPlan.id)).where(FloorPlan.entity_id == entity_id)):
        raise RuleViolation(f"Entity {entity_id} already has a floor plan")
    processed = _process_floorplan_upload(data)
    plan = FloorPlan(
        entity_id=entity_id,
        image_path=processed.file_path,
        image_w=processed.width,
        image_h=processed.height,
    )
    db.add(plan)
    db.commit()
    return plan


def replace_floor_image(db: Session, floor_id: int, data: bytes) -> FloorPlan:
    """Swap the image, KEEPING regions (the client warns about re-tracing —
    existing polygons are in the old image's pixel space)."""
    plan = _get_floor(db, floor_id)
    old_path = plan.image_path
    processed = _process_floorplan_upload(data)
    plan.image_path = processed.file_path
    plan.image_w = processed.width
    plan.image_h = processed.height
    db.commit()
    if old_path != plan.image_path:
        media.delete_floorplan_if_unreferenced(db, old_path)
    return plan


def set_floor_sort(db: Session, floor_id: int, sort_order: int) -> FloorPlan:
    plan = _get_floor(db, floor_id)
    plan.sort_order = sort_order
    db.commit()
    return plan


def delete_floor(db: Session, floor_id: int) -> None:
    """Delete the plan (regions cascade); the image file is unlinked only if no
    other floor still references the same content-addressed path."""
    plan = _get_floor(db, floor_id)
    image_path = plan.image_path
    db.delete(plan)
    db.commit()
    media.delete_floorplan_if_unreferenced(db, image_path)


# --- regions ------------------------------------------------------------------


def list_regions(db: Session, floor_id: int) -> list[tuple[MapRegion, Entity]]:
    """Regions of a floor, EXCLUDING rooms that are archived or inside an
    archived subtree — the region row itself is kept, so the trace reappears
    as-is on unarchive (archiving hides, it never destroys)."""
    _get_floor(db, floor_id)
    rows = db.execute(
        select(MapRegion, Entity)
        .join(Entity, Entity.id == MapRegion.entity_id)
        .where(MapRegion.floor_plan_id == floor_id, tree.not_in_archived_subtree())
        .order_by(MapRegion.id)
    )
    return [(region, entity) for region, entity in rows]


def _validate_polygon(polygon: list[list[float]], plan: FloorPlan) -> None:
    if len(polygon) < 3:
        raise RuleViolation("A region polygon needs at least 3 points")
    # Reject non-finite coordinates explicitly, BEFORE the bounds pass: NaN
    # comparisons are always False, so a NaN only fails the bounds check by
    # accident of its phrasing, and when image_w/image_h are unknown there is
    # no bounds check at all. A committed NaN/inf would then 500 every
    # floor-detail GET (starlette's JSONResponse refuses non-finite floats).
    for x, y in polygon:
        if not (math.isfinite(x) and math.isfinite(y)):
            raise RuleViolation(f"Polygon point ({x}, {y}) is not a finite coordinate")
    if plan.image_w is None or plan.image_h is None:
        return
    for x, y in polygon:
        if not (
            -POLYGON_TOLERANCE <= x <= plan.image_w + POLYGON_TOLERANCE
            and -POLYGON_TOLERANCE <= y <= plan.image_h + POLYGON_TOLERANCE
        ):
            raise RuleViolation(
                f"Polygon point ({x}, {y}) is outside the floor-plan image "
                f"({plan.image_w}x{plan.image_h})"
            )


def _validate_label_anchor(
    plan: FloorPlan, label_x: float | None, label_y: float | None
) -> None:
    """Label anchors follow the polygon-point rules: finite and inside the
    image with the same ±POLYGON_TOLERANCE slack. Checked BEFORE commit — a
    stored NaN/inf would make every floor-detail GET 500 (JSONResponse is
    strict JSON, allow_nan=False)."""
    for name, value, limit in (
        ("label_x", label_x, plan.image_w),
        ("label_y", label_y, plan.image_h),
    ):
        if value is None:
            continue
        if not math.isfinite(value):
            raise RuleViolation(f"{name} must be a finite number")
        if limit is not None and not (-POLYGON_TOLERANCE <= value <= limit + POLYGON_TOLERANCE):
            raise RuleViolation(
                f"{name} ({value}) is outside the floor-plan image "
                f"({plan.image_w}x{plan.image_h})"
            )


def upsert_region(
    db: Session,
    floor_id: int,
    entity_id: int,
    polygon: list[list[float]],
    label_x: float | None = None,
    label_y: float | None = None,
) -> MapRegion:
    plan = _get_floor(db, floor_id)
    entity = _get_entity(db, entity_id)
    if entity.kind != "space":
        raise RuleViolation(f"A region must trace a space, not a {entity.kind}")
    floor_entity = db.get(Entity, plan.entity_id)
    # Strict descendant: the trailing '/' in path prevents id-prefix traps.
    if entity.id == floor_entity.id or not entity.path.startswith(floor_entity.path):
        raise RuleViolation(
            f"Region entity must be a descendant of the floor's space ({floor_entity.name})"
        )
    _validate_polygon(polygon, plan)
    _validate_label_anchor(plan, label_x, label_y)

    region = db.scalar(
        select(MapRegion).where(
            MapRegion.floor_plan_id == floor_id, MapRegion.entity_id == entity_id
        )
    )
    if region is None:
        region = MapRegion(floor_plan_id=floor_id, entity_id=entity_id)
        db.add(region)
    region.polygon_json = json.dumps(polygon)
    region.label_x = label_x
    region.label_y = label_y
    db.commit()
    return region


def delete_region(db: Session, floor_id: int, entity_id: int) -> None:
    _get_floor(db, floor_id)
    region = db.scalar(
        select(MapRegion).where(
            MapRegion.floor_plan_id == floor_id, MapRegion.entity_id == entity_id
        )
    )
    if region is None:
        raise NotFoundError(f"No region for entity {entity_id} on floor {floor_id}")
    db.delete(region)
    db.commit()


# --- grids --------------------------------------------------------------------


def list_grids(db: Session, entity_id: int) -> list[FurnitureGrid]:
    """All grids RENDERING this entity — includes sub-grids anchored on other
    grids' cells (their entity_id is the cell's bound container)."""
    _get_entity(db, entity_id)
    stmt = (
        select(FurnitureGrid)
        .where(FurnitureGrid.entity_id == entity_id)
        .order_by(FurnitureGrid.sort_order, FurnitureGrid.id)
    )
    return list(db.scalars(stmt))


def cells_for_grids(db: Session, grid_ids: list[int]) -> dict[int, list[GridCell]]:
    """{grid_id: cells ordered by (row, col)} — single query."""
    if not grid_ids:
        return {}
    out: dict[int, list[GridCell]] = {}
    for cell in db.scalars(
        select(GridCell)
        .where(GridCell.grid_id.in_(grid_ids))
        .order_by(GridCell.grid_id, GridCell.row, GridCell.col)
    ):
        out.setdefault(cell.grid_id, []).append(cell)
    return out


def _check_grid_size(rows: int, cols: int) -> None:
    if not (1 <= rows <= GRID_MAX and 1 <= cols <= GRID_MAX):
        raise RuleViolation(f"Grid size must be between 1x1 and {GRID_MAX}x{GRID_MAX}")


def create_grid(
    db: Session,
    *,
    entity_id: int | None,
    rows: int,
    cols: int,
    name: str | None = None,
    parent_cell_id: int | None = None,
    default_cell_type: str = "shelf",
) -> FurnitureGrid:
    _check_grid_size(rows, cols)
    if default_cell_type not in CELL_TYPES:
        raise RuleViolation(f"Unknown cell type {default_cell_type!r}")

    if parent_cell_id is not None:
        parent_cell = _get_cell(db, parent_cell_id)
        if parent_cell.entity_id is None:
            raise RuleViolation(
                "Bind the parent cell to a container before adding an inner layout"
            )
        if entity_id is None:
            entity_id = parent_cell.entity_id  # sub-grid renders the cell's entity
        elif entity_id != parent_cell.entity_id:
            raise RuleViolation("A sub-grid must render the parent cell's bound entity")
    if entity_id is None:
        raise RuleViolation("entity_id is required unless parent_cell_id is given")

    entity = _get_entity(db, entity_id)
    if entity.kind not in ("furniture", "container"):
        raise RuleViolation(
            f"A layout grid belongs on a furniture or container, not a {entity.kind}"
        )

    grid = FurnitureGrid(
        entity_id=entity_id, name=name, rows=rows, cols=cols, parent_cell_id=parent_cell_id
    )
    db.add(grid)
    db.flush()  # assigns grid.id for the cells
    db.add_all(
        GridCell(grid_id=grid.id, row=r, col=c, cell_type=default_cell_type)
        for r in range(rows)
        for c in range(cols)
    )
    db.commit()
    return grid


def update_grid(db: Session, grid_id: int, changes: dict) -> FurnitureGrid:
    """Patch name/sort_order; a rows/cols change grows (new 'shelf' cells) or
    shrinks — shrinking deletes only UNBOUND dropped cells, 409 otherwise, and
    clamps surviving spans into the new bounds."""
    grid = _get_grid(db, grid_id)
    for field in ("name", "sort_order"):
        if field in changes:
            setattr(grid, field, changes[field])

    new_rows = changes.get("rows", grid.rows)
    new_cols = changes.get("cols", grid.cols)
    if (new_rows, new_cols) != (grid.rows, grid.cols):
        _check_grid_size(new_rows, new_cols)
        cells = list(db.scalars(select(GridCell).where(GridCell.grid_id == grid.id)))
        dropped = [c for c in cells if c.row >= new_rows or c.col >= new_cols]
        bound = [c for c in dropped if c.entity_id is not None]
        if bound:
            spots = ", ".join(f"({c.row + 1}-{c.col + 1})" for c in bound)
            raise RuleViolation(f"Resize would drop bound cell(s) at {spots}; unbind first")
        dropped_ids = {c.id for c in dropped}
        for cell in cells:
            if cell.id in dropped_ids:
                db.delete(cell)  # unbound: safe to drop (no sub-grid can anchor here)
            else:
                cell.row_span = min(cell.row_span, new_rows - cell.row)
                cell.col_span = min(cell.col_span, new_cols - cell.col)
        kept = {(c.row, c.col) for c in cells if c.id not in dropped_ids}
        db.add_all(
            GridCell(grid_id=grid.id, row=r, col=c)
            for r in range(new_rows)
            for c in range(new_cols)
            if (r, c) not in kept
        )
        grid.rows, grid.cols = new_rows, new_cols
    db.commit()
    return grid


def delete_grid(db: Session, grid_id: int) -> None:
    """Delete the grid; cells cascade (and sub-grids anchored on them cascade
    recursively). Bound entities are NOT deleted — the binding is a view link."""
    grid = _get_grid(db, grid_id)
    db.delete(grid)
    db.commit()


# --- cells --------------------------------------------------------------------


def _validate_cell_rect(db: Session, grid: FurnitureGrid, cell: GridCell) -> None:
    """Bounds + occupied-area matrix check. Void cells are holes: they occupy
    nothing and a void cell itself only needs to stay inside the grid."""
    if cell.row + cell.row_span > grid.rows or cell.col + cell.col_span > grid.cols:
        raise RuleViolation(
            f"Cell span exceeds the {grid.rows}x{grid.cols} grid bounds"
        )
    if cell.cell_type == "void":
        return
    occupied = [[False] * grid.cols for _ in range(grid.rows)]
    others = db.scalars(
        select(GridCell).where(
            GridCell.grid_id == grid.id,
            GridCell.id != cell.id,
            GridCell.cell_type != "void",
        )
    )
    for other in others:
        for r in range(other.row, min(other.row + other.row_span, grid.rows)):
            for c in range(other.col, min(other.col + other.col_span, grid.cols)):
                occupied[r][c] = True
    for r in range(cell.row, cell.row + cell.row_span):
        for c in range(cell.col, cell.col + cell.col_span):
            if occupied[r][c]:
                raise RuleViolation(
                    f"Cell span overlaps the cell occupying row {r + 1}, column {c + 1} "
                    "(mark covered cells as 'void' first)"
                )


def update_cell(db: Session, cell_id: int, changes: dict) -> GridCell:
    cell = _get_cell(db, cell_id)
    for field in ("cell_type", "label", "row_span", "col_span"):
        if field in changes:
            setattr(cell, field, changes[field])
    if cell.cell_type not in CELL_TYPES:
        raise RuleViolation(f"Unknown cell type {cell.cell_type!r}")
    # A void is a hole with no face — it cannot keep rendering a container.
    if cell.cell_type == "void" and cell.entity_id is not None:
        raise RuleViolation("Cannot make a bound cell 'void' — unbind it first")
    grid = db.get(FurnitureGrid, cell.grid_id)
    _validate_cell_rect(db, grid, cell)
    db.commit()
    return cell


def _guard_subgrid_anchor(db: Session, cell: GridCell) -> None:
    """Refuse to change a binding that a sub-grid is anchored on — the sub-grid
    must keep rendering the cell's bound entity (delete the inner layout first)."""
    anchored = db.scalar(
        select(func.count(FurnitureGrid.id)).where(FurnitureGrid.parent_cell_id == cell.id)
    )
    if anchored:
        raise RuleViolation(
            "Cell anchors an inner layout; delete the sub-grid before rebinding"
        )


def bind_cell(
    db: Session, cell_id: int, *, entity_id: int | None = None, auto: bool = False
) -> GridCell:
    """Three forms per contract: auto (create + bind a container child named
    from the label or '<CellType> <row+1>-<col+1>'), an existing direct-child
    container id, or None to unbind (entity untouched).

    Auto on an ALREADY-BOUND cell is refused (it would mint a brand-new
    container and silently orphan the current binding); an explicit entity_id
    rebind of a bound cell stays allowed — that is an intentional replace."""
    cell = _get_cell(db, cell_id)
    grid = db.get(FurnitureGrid, cell.grid_id)

    # Voids are holes a neighbour's span covers — no face, nothing to bind.
    # (Unbinding, entity_id=None, stays a no-op for symmetry.)
    if (auto or entity_id is not None) and cell.cell_type == "void":
        raise RuleViolation("A void cell cannot be bound — change its type first")

    if auto:
        if cell.entity_id is not None:
            raise RuleViolation("Cell is already bound — unbind first")
        name = (cell.label or "").strip() or (
            f"{cell.cell_type.capitalize()} {cell.row + 1}-{cell.col + 1}"
        )
        entity = tree.create_entity(
            db, name=name, kind="container", parent_id=grid.entity_id, commit=False
        )
        cell.entity_id = entity.id
        db.commit()
        return cell

    if entity_id is None:
        if cell.entity_id is not None:
            _guard_subgrid_anchor(db, cell)
            cell.entity_id = None
            db.commit()
        return cell

    entity = _get_entity(db, entity_id)
    if cell.entity_id == entity_id:
        return cell  # idempotent re-bind
    _guard_subgrid_anchor(db, cell)
    if entity.kind != "container" or entity.parent_id != grid.entity_id:
        raise RuleViolation(
            "A cell must bind a container that is a direct child of the grid's entity"
        )
    if entity.archived_at is not None:
        # The map shows the live house; an archived box has (virtually) left it.
        raise RuleViolation("Cannot bind an archived container — unarchive it first")
    cell.entity_id = entity_id
    try:
        db.commit()
    except IntegrityError:
        # UNIQUE(grid_cell.entity_id): the container already renders in a cell.
        db.rollback()
        raise RuleViolation(f"Entity {entity_id} is already bound to another cell")
    return cell
