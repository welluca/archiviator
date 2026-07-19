"""House-map ORM models (M8): floor plans, room regions, furniture grids, cells.

The map is a VIEW LAYER over the entity tree: floor_plan binds a space to a
plan image, map_region traces a descendant room space as a polygon on that
image, and furniture_grid/grid_cell render a furniture/container front as
rows x cols of drawers/shelves/doors. Every binding is by entity id, so
contents, breadcrumbs, search and QR flows keep working through the tree —
and deleting map rows never deletes entities.

polygon_json stores '[[x,y],...]' in IMAGE-PIXEL coordinates (scale-free on
the client via the SVG viewBox). floor_plan.image_path is a content-addressed
relative path under data_dir ('floorplans/{hh}/{sha256}.jpg') — several floors
may share one file, so deletes go through
media.delete_floorplan_if_unreferenced.
"""

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CELL_TYPES = ("drawer", "shelf", "door", "box", "void", "other")


class FloorPlan(Base):
    """One plan per space (UNIQUE entity_id); the entity is the floor's SPACE
    node. image_w/image_h are the FIXED canvas coordinate space (the SVG
    viewBox): set once at creation and never rescaled by an image swap, so
    regions and placements stay put when an image is added/removed/replaced.
    image_path is NULL for a blank-canvas floor (drawn in-app, no image)."""

    __tablename__ = "floor_plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), unique=True
    )
    image_path: Mapped[str | None] = mapped_column(Text)
    image_w: Mapped[int | None] = mapped_column(Integer)
    image_h: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<FloorPlan {self.id} entity={self.entity_id}>"


class MapRegion(Base):
    """A traced room: a polygon on a floor plan bound to a ROOM space node that
    is a descendant of the floor's space (service-enforced). label_x/label_y is
    an optional label anchor; the client falls back to the polygon centroid."""

    __tablename__ = "map_region"
    __table_args__ = (
        UniqueConstraint("floor_plan_id", "entity_id", name="uq_map_region_floor_entity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    floor_plan_id: Mapped[int] = mapped_column(
        ForeignKey("floor_plan.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), index=True
    )
    polygon_json: Mapped[str] = mapped_column(Text)
    label_x: Mapped[float | None] = mapped_column(Float)
    label_y: Mapped[float | None] = mapped_column(Float)

    def __repr__(self) -> str:
        return f"<MapRegion {self.id} floor={self.floor_plan_id} entity={self.entity_id}>"


class FurniturePlacement(Base):
    """A furniture/container footprint on the top-view floor: an axis-aligned
    box in CANVAS coordinates (same space as MapRegion polygons). entity_id is
    a NON-space descendant of the floor's space (service-enforced) and at most
    one footprint per (floor, entity). Clicking it drills into the entity's
    FurnitureGrid front view. rotation is stored for forward-compat (degrees
    clockwise about the box centre) but the v1 UI keeps every box axis-aligned.
    label_x/label_y is an optional label anchor (client falls back to centre)."""

    __tablename__ = "map_placement"
    __table_args__ = (
        UniqueConstraint(
            "floor_plan_id", "entity_id", name="uq_map_placement_floor_entity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    floor_plan_id: Mapped[int] = mapped_column(
        ForeignKey("floor_plan.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), index=True
    )
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    rotation: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    label_x: Mapped[float | None] = mapped_column(Float)
    label_y: Mapped[float | None] = mapped_column(Float)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<FurniturePlacement {self.id} floor={self.floor_plan_id} entity={self.entity_id}>"


class FurnitureGrid(Base):
    """A rows x cols front rendered for a furniture/container entity ('Front',
    'Inside left door', ...). A sub-grid (parent_cell_id set) is anchored on a
    BOUND cell of another grid and must render that cell's bound entity —
    use_alter breaks the grid <-> cell FK cycle at DDL level (same pattern as
    entity.cover_attachment_id)."""

    __tablename__ = "furniture_grid"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(Text)
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    parent_cell_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "grid_cell.id",
            ondelete="CASCADE",
            use_alter=True,
            name="fk_furniture_grid_parent_cell",
        ),
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<FurnitureGrid {self.id} entity={self.entity_id} {self.rows}x{self.cols}>"


class GridCell(Base):
    """One cell of a grid, anchored at 0-based (row, col) with spans. entity_id
    is a 1:1 view binding to a direct-child container of the grid's entity
    (UNIQUE — a container renders in at most one cell; SET NULL on entity
    delete). 'void' cells are holes that spans of neighbouring cells may cover."""

    __tablename__ = "grid_cell"
    __table_args__ = (
        CheckConstraint(
            "cell_type IN ('drawer','shelf','door','box','void','other')",
            name="ck_grid_cell_type",
        ),
        UniqueConstraint("grid_id", "row", "col", name="uq_grid_cell_grid_row_col"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    grid_id: Mapped[int] = mapped_column(
        ForeignKey("furniture_grid.id", ondelete="CASCADE"), index=True
    )
    row: Mapped[int] = mapped_column(Integer)
    col: Mapped[int] = mapped_column(Integer)
    row_span: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    col_span: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    cell_type: Mapped[str] = mapped_column(Text, default="shelf", server_default="shelf")
    label: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("entity.id", ondelete="SET NULL"), unique=True
    )

    def __repr__(self) -> str:
        return f"<GridCell {self.id} grid={self.grid_id} ({self.row},{self.col})>"
