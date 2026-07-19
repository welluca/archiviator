"""House-map router (M8): floor plans, room regions, furniture grids, cell binds.

Thin REST surface over app.services.mapsvc. Floor-plan images are served from
'/media/floorplans/…' (content-addressed, unauthenticated — same tradeoff as
attachments, documented in app/routers/media.py).
"""

import json
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.dependencies import DbSession, get_current_user
from app.models.entity import Entity
from app.models.map import FloorPlan, FurnitureGrid, GridCell, MapRegion
from app.routers.attachments import domain_errors
from app.services import mapsvc as svc
from app.services import media, tree

router = APIRouter(dependencies=[Depends(get_current_user)])

CellType = Literal["drawer", "shelf", "door", "box", "void", "other"]


class FloorEntityOut(BaseModel):
    id: int
    name: str
    breadcrumb: str


class BoundEntityOut(BaseModel):
    """Entity brief for regions and bound cells: counts drive the UI pills."""

    id: int
    name: str
    child_count: int
    item_count: int


class FloorOut(BaseModel):
    id: int
    entity: FloorEntityOut
    image_url: str
    image_w: int | None
    image_h: int | None
    sort_order: int
    region_count: int


class RegionOut(BaseModel):
    id: int
    entity: BoundEntityOut
    polygon: list[list[float]]
    label_x: float | None
    label_y: float | None


class FloorDetailOut(FloorOut):
    regions: list[RegionOut]


class FloorSortUpdate(BaseModel):
    sort_order: int


class RegionPut(BaseModel):
    # A hand-traced room needs tens of points; 500 is far beyond any real shape
    # and caps the JSON blob a client can persist per region.
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=500)
    label_x: float | None = None
    label_y: float | None = None


class CellOut(BaseModel):
    id: int
    row: int
    col: int
    row_span: int
    col_span: int
    cell_type: CellType
    label: str | None
    entity: BoundEntityOut | None


class GridOut(BaseModel):
    id: int
    name: str | None
    rows: int
    cols: int
    parent_cell_id: int | None
    sort_order: int
    cells: list[CellOut]


class GridCreate(BaseModel):
    entity_id: int | None = None  # optional ONLY for sub-grids (taken from the cell)
    rows: int = Field(ge=1, le=svc.GRID_MAX)
    cols: int = Field(ge=1, le=svc.GRID_MAX)
    name: str | None = None
    parent_cell_id: int | None = None
    default_cell_type: CellType = "shelf"

    @model_validator(mode="after")
    def _entity_or_parent_cell(self) -> "GridCreate":
        if self.entity_id is None and self.parent_cell_id is None:
            raise ValueError("entity_id is required unless parent_cell_id is given")
        return self


class GridPatch(BaseModel):
    name: str | None = None
    rows: int | None = Field(default=None, ge=1, le=svc.GRID_MAX)
    cols: int | None = Field(default=None, ge=1, le=svc.GRID_MAX)
    sort_order: int | None = None

    @field_validator("rows", "cols", "sort_order")
    @classmethod
    def _not_null(cls, v: int | None) -> int:
        # Optional in the payload, but an explicit null would hit NOT NULL columns.
        if v is None:
            raise ValueError("field must be an integer, not null")
        return v


class CellPatch(BaseModel):
    cell_type: CellType | None = None
    label: str | None = None
    row_span: int | None = Field(default=None, ge=1)
    col_span: int | None = Field(default=None, ge=1)

    @field_validator("cell_type", "row_span", "col_span")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("field must not be null")
        return v


class BindRequest(BaseModel):
    entity_id: int | None = None
    auto: bool = False

    @model_validator(mode="after")
    def _one_form(self) -> "BindRequest":
        if self.auto and self.entity_id is not None:
            raise ValueError("pass either auto or entity_id, not both")
        return self


# --- shaping helpers ----------------------------------------------------------


def _floor_out(plan: FloorPlan, entity: Entity, region_count: int) -> FloorOut:
    return FloorOut(
        id=plan.id,
        entity=FloorEntityOut(id=entity.id, name=entity.name, breadcrumb=entity.breadcrumb),
        image_url=f"/media/{plan.image_path}",
        image_w=plan.image_w,
        image_h=plan.image_h,
        sort_order=plan.sort_order,
        region_count=region_count,
    )


def _single_floor_out(db: Session, plan: FloorPlan) -> FloorOut:
    entity = db.get(Entity, plan.entity_id)
    return _floor_out(plan, entity, svc.region_counts(db, [plan.id]).get(plan.id, 0))


def _bound_entity_out(
    entity: Entity, child_counts: dict[int, int], items: dict[int, int]
) -> BoundEntityOut:
    return BoundEntityOut(
        id=entity.id,
        name=entity.name,
        child_count=child_counts.get(entity.id, 0),
        item_count=items.get(entity.id, 0),
    )


def _region_out(
    region: MapRegion, entity: Entity, child_counts: dict[int, int], items: dict[int, int]
) -> RegionOut:
    return RegionOut(
        id=region.id,
        entity=_bound_entity_out(entity, child_counts, items),
        polygon=json.loads(region.polygon_json),
        label_x=region.label_x,
        label_y=region.label_y,
    )


def _grids_out(db: Session, grids: list[FurnitureGrid]) -> list[GridOut]:
    """Shape grids + cells with bound-entity counts — batched, no N+1."""
    cells_map = svc.cells_for_grids(db, [g.id for g in grids])
    bound_ids = [c.entity_id for cells in cells_map.values() for c in cells if c.entity_id]
    entities = (
        {e.id: e for e in db.scalars(select(Entity).where(Entity.id.in_(bound_ids)))}
        if bound_ids
        else {}
    )
    child_counts = tree.child_counts(db, list(entities))
    # Cell pills count INCLUDING archived (matching child_counts): the physical
    # drawer still holds the archived box, so its contents don't vanish from the
    # front view. Floor-region pills deliberately differ — they keep the default
    # archived-excluded item_count of the inventory views.
    items = svc.item_counts(db, list(entities.values()), include_archived=True)
    return [
        GridOut(
            id=g.id,
            name=g.name,
            rows=g.rows,
            cols=g.cols,
            parent_cell_id=g.parent_cell_id,
            sort_order=g.sort_order,
            cells=[
                _cell_out(c, entities.get(c.entity_id), child_counts, items)
                for c in cells_map.get(g.id, [])
            ],
        )
        for g in grids
    ]


def _cell_out(
    cell: GridCell,
    entity: Entity | None,
    child_counts: dict[int, int],
    items: dict[int, int],
) -> CellOut:
    return CellOut(
        id=cell.id,
        row=cell.row,
        col=cell.col,
        row_span=cell.row_span,
        col_span=cell.col_span,
        cell_type=cell.cell_type,
        label=cell.label,
        entity=None if entity is None else _bound_entity_out(entity, child_counts, items),
    )


def _single_cell_out(db: Session, cell: GridCell) -> CellOut:
    entity = db.get(Entity, cell.entity_id) if cell.entity_id is not None else None
    if entity is None:
        return _cell_out(cell, None, {}, {})
    # include_archived: same counting rule as the batched _grids_out pills.
    return _cell_out(
        cell,
        entity,
        tree.child_counts(db, [entity.id]),
        svc.item_counts(db, [entity], include_archived=True),
    )


# --- floors -------------------------------------------------------------------


@router.get("/map/floors", response_model=list[FloorOut])
async def list_floors(db: DbSession):
    plans = svc.list_floors(db)
    entities = (
        {
            e.id: e
            for e in db.scalars(
                select(Entity).where(Entity.id.in_([p.entity_id for p in plans]))
            )
        }
        if plans
        else {}
    )
    counts = svc.region_counts(db, [p.id for p in plans])
    return [_floor_out(p, entities[p.entity_id], counts.get(p.id, 0)) for p in plans]


@router.post("/map/floors", response_model=FloorOut, status_code=status.HTTP_201_CREATED)
async def create_floor(
    db: DbSession,
    file: UploadFile = File(...),
    entity_id: int = Form(...),
):
    # Read at most MAX_UPLOAD + 1 bytes: one byte over the cap is proof enough for 413.
    data = await file.read(media.MAX_UPLOAD + 1)
    with domain_errors():
        plan = svc.create_floor(db, entity_id, data)
    return _single_floor_out(db, plan)


@router.get("/map/floors/{floor_id}", response_model=FloorDetailOut)
async def get_floor(floor_id: int, db: DbSession):
    with domain_errors():
        plan = svc.get_floor(db, floor_id)
        pairs = svc.list_regions(db, floor_id)
    region_entities = [entity for _, entity in pairs]
    child_counts = tree.child_counts(db, [e.id for e in region_entities])
    items = svc.item_counts(db, region_entities)
    base = _floor_out(plan, db.get(Entity, plan.entity_id), len(pairs))
    return FloorDetailOut(
        **base.model_dump(),
        regions=[_region_out(r, e, child_counts, items) for r, e in pairs],
    )


@router.patch("/map/floors/{floor_id}", response_model=FloorOut)
async def update_floor(floor_id: int, request: Request, db: DbSession):
    """Multipart 'file' replaces the image (regions KEPT — the client warns
    about re-tracing); a JSON body updates {sort_order}. Handled manually
    because FastAPI cannot declare a multipart-or-JSON body on one endpoint."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        # request.form() yields starlette's UploadFile (FastAPI's is a subclass
        # only used for declared parameters), so check against the base type.
        if not isinstance(upload, StarletteUploadFile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Multipart body must include a 'file' upload",
            )
        data = await upload.read(media.MAX_UPLOAD + 1)
        with domain_errors():
            plan = svc.replace_floor_image(db, floor_id, data)
    else:
        try:
            payload = FloorSortUpdate.model_validate(await request.json())
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=exc.errors(include_url=False),
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Body must be JSON {sort_order} or multipart with 'file'",
            )
        with domain_errors():
            plan = svc.set_floor_sort(db, floor_id, payload.sort_order)
    return _single_floor_out(db, plan)


@router.delete("/map/floors/{floor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_floor(floor_id: int, db: DbSession):
    with domain_errors():
        svc.delete_floor(db, floor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- regions ------------------------------------------------------------------


@router.put("/map/floors/{floor_id}/regions/{entity_id}", response_model=RegionOut)
async def put_region(floor_id: int, entity_id: int, payload: RegionPut, db: DbSession):
    with domain_errors():
        region = svc.upsert_region(
            db,
            floor_id,
            entity_id,
            [[x, y] for x, y in payload.polygon],
            payload.label_x,
            payload.label_y,
        )
    entity = db.get(Entity, entity_id)
    return _region_out(
        region, entity, tree.child_counts(db, [entity.id]), svc.item_counts(db, [entity])
    )


@router.delete(
    "/map/floors/{floor_id}/regions/{entity_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_region(floor_id: int, entity_id: int, db: DbSession):
    with domain_errors():
        svc.delete_region(db, floor_id, entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- grids --------------------------------------------------------------------


@router.get("/map/grids", response_model=list[GridOut])
async def list_grids(entity_id: int, db: DbSession):
    with domain_errors():
        grids = svc.list_grids(db, entity_id)
    return _grids_out(db, grids)


@router.post("/map/grids", response_model=GridOut, status_code=status.HTTP_201_CREATED)
async def create_grid(payload: GridCreate, db: DbSession):
    with domain_errors():
        grid = svc.create_grid(
            db,
            entity_id=payload.entity_id,
            rows=payload.rows,
            cols=payload.cols,
            name=payload.name,
            parent_cell_id=payload.parent_cell_id,
            default_cell_type=payload.default_cell_type,
        )
    return _grids_out(db, [grid])[0]


@router.patch("/map/grids/{grid_id}", response_model=GridOut)
async def update_grid(grid_id: int, payload: GridPatch, db: DbSession):
    with domain_errors():
        grid = svc.update_grid(db, grid_id, payload.model_dump(exclude_unset=True))
    return _grids_out(db, [grid])[0]


@router.delete("/map/grids/{grid_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_grid(grid_id: int, db: DbSession):
    with domain_errors():
        svc.delete_grid(db, grid_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- cells --------------------------------------------------------------------


@router.patch("/map/cells/{cell_id}", response_model=CellOut)
async def update_cell(cell_id: int, payload: CellPatch, db: DbSession):
    with domain_errors():
        cell = svc.update_cell(db, cell_id, payload.model_dump(exclude_unset=True))
    return _single_cell_out(db, cell)


@router.post("/map/cells/{cell_id}/bind", response_model=CellOut)
async def bind_cell(cell_id: int, payload: BindRequest, db: DbSession):
    with domain_errors():
        cell = svc.bind_cell(db, cell_id, entity_id=payload.entity_id, auto=payload.auto)
    return _single_cell_out(db, cell)
