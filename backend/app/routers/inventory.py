"""Inventory router (M6): quantity adjustment plus the dashboard queries
(low-stock, valuation, recent). Thin surface over app.services.inventory;
entity-shaped responses reuse the EntityOut batch helpers."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import DbSession, get_current_user
from app.routers.entities import (
    EntityOut,
    _out,
    _single_out,
    _tags_map,
    _thumb_map,
    domain_errors,
)
from app.services import inventory as svc
from app.services import tree

router = APIRouter(dependencies=[Depends(get_current_user)])


class QuantityAdjust(BaseModel):
    delta: float


class EntityBrief(BaseModel):
    id: int
    name: str


class CategoryBrief(BaseModel):
    id: int
    name: str


class RootValuation(BaseModel):
    entity: EntityBrief
    total: float
    insured_total: float


class CategoryValuation(BaseModel):
    category: CategoryBrief | None
    total: float
    insured_total: float


class ValuationOut(BaseModel):
    total: float
    insured_total: float
    # Instance default currency the totals are denominated in, plus how many
    # contributing entities carry a DIFFERENT currency (summed numerically).
    currency: str
    mixed_currency_count: int
    by_root: list[RootValuation]
    by_category: list[CategoryValuation]


def _list_out(db, entities) -> list[EntityOut]:
    counts = tree.child_counts(db, [e.id for e in entities])
    inbox_id = tree.get_inbox_id(db)
    thumbs = _thumb_map(db, entities)
    tags = _tags_map(db, entities)
    return [_out(e, counts, inbox_id, thumbs, tags) for e in entities]


@router.post("/entities/{entity_id}/quantity-adjust", response_model=EntityOut)
async def quantity_adjust(entity_id: int, payload: QuantityAdjust, db: DbSession):
    with domain_errors():
        entity = svc.adjust_quantity(db, entity_id, payload.delta)
    return _single_out(db, entity)


@router.get("/inventory/low-stock", response_model=list[EntityOut])
async def low_stock(db: DbSession):
    return _list_out(db, svc.low_stock(db))


@router.get("/inventory/valuation", response_model=ValuationOut)
async def valuation(db: DbSession):
    return svc.valuation(db)


@router.get("/inventory/recent", response_model=list[EntityOut])
async def recent(db: DbSession):
    return _list_out(db, svc.recent(db))
