"""Entities router: thin REST surface over app.services.tree (M2 containment tree)."""

import re
from contextlib import contextmanager
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import DbSession, get_current_user
from app.models.attachment import Attachment
from app.models.entity import Entity
from app.models.metadata import EntityTag, Tag
from app.services import metadata as metadata_svc
from app.services import tree

router = APIRouter(dependencies=[Depends(get_current_user)])

Kind = Literal["space", "furniture", "container", "item"]


class EntityCreate(BaseModel):
    name: str = Field(min_length=1)
    kind: Kind
    parent_id: int | None = None
    subtype: str | None = None
    description: str | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    subtype: str | None = None
    description: str | None = None
    notes: str | None = None
    category_id: int | None = None
    # Inventory fields (M6). Explicit null clears the nullable ones; the NOT
    # NULL columns (quantity, is_consumable, insured, warranty_lifetime) reject
    # explicit null with 422 instead.
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    is_consumable: bool | None = None
    low_stock_threshold: float | None = Field(default=None, ge=0)
    purchase_date: str | None = None
    purchase_price: float | None = Field(default=None, ge=0)
    purchase_from: str | None = None
    currency: str | None = None
    current_value: float | None = Field(default=None, ge=0)
    insured: bool | None = None
    warranty_expires: str | None = None
    warranty_lifetime: bool | None = None
    warranty_notes: str | None = None
    serial_number: str | None = None
    model_number: str | None = None
    manufacturer: str | None = None
    sold_date: str | None = None
    sold_to: str | None = None
    sold_price: float | None = Field(default=None, ge=0)
    sold_notes: str | None = None

    @field_validator("name")
    @classmethod
    def _non_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("quantity", "is_consumable", "insured", "warranty_lifetime")
    @classmethod
    def _not_null(cls, v):
        # Optional in the payload, but an explicit null would hit NOT NULL columns.
        if v is None:
            raise ValueError("field must not be null")
        return v

    @field_validator("purchase_date", "warranty_expires", "sold_date")
    @classmethod
    def _iso_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _DATE_RE.match(v):
            raise ValueError("must be an ISO date (YYYY-MM-DD)")
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"{v!r} is not a valid date")
        return v

    @field_validator("currency")
    @classmethod
    def _currency_code(cls, v: str | None) -> str | None:
        # Strict: 3-letter UPPERCASE or null (null = default currency).
        if v is None:
            return v
        if not _CURRENCY_RE.match(v):
            raise ValueError("must be a 3-letter uppercase currency code (e.g. EUR)")
        return v


class MoveRequest(BaseModel):
    parent_id: int | None


class TagBrief(BaseModel):
    id: int
    name: str
    color: str | None


class EntityOut(BaseModel):
    id: int
    kind: str
    subtype: str | None
    name: str
    description: str | None
    notes: str | None
    parent_id: int | None
    category_id: int | None
    depth: int
    breadcrumb: str
    asset_tag: str | None
    draft: bool
    archived: bool
    protected: bool
    child_count: int
    cover_attachment_id: int | None
    thumb_url: str | None
    tags: list[TagBrief]
    # Inventory fields (M6) — keep in sync with tree.INVENTORY_FIELDS.
    quantity: float
    unit: str | None
    is_consumable: bool
    low_stock_threshold: float | None
    purchase_date: str | None
    purchase_price: float | None
    purchase_from: str | None
    currency: str | None
    current_value: float | None
    insured: bool
    warranty_expires: str | None
    warranty_lifetime: bool
    warranty_notes: str | None
    serial_number: str | None
    model_number: str | None
    manufacturer: str | None
    sold_date: str | None
    sold_to: str | None
    sold_price: float | None
    sold_notes: str | None
    created_at: datetime
    updated_at: datetime


class PathSegment(BaseModel):
    id: int
    name: str
    kind: str


@contextmanager
def domain_errors():
    """Translate tree.py domain exceptions to HTTP errors."""
    try:
        yield
    except tree.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except tree.RuleViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _thumb_map(db: Session, entities: list[Entity]) -> dict[int, str]:
    """{attachment_id: thumb_path} for the entities' covers — ONE IN query, no N+1."""
    cover_ids = {e.cover_attachment_id for e in entities if e.cover_attachment_id is not None}
    if not cover_ids:
        return {}
    rows = db.execute(
        select(Attachment.id, Attachment.thumb_path).where(Attachment.id.in_(cover_ids))
    )
    return {att_id: thumb for att_id, thumb in rows if thumb}


def _tags_map(db: Session, entities: list[Entity]) -> dict[int, list[TagBrief]]:
    """{entity_id: [TagBrief]} name-ordered — ONE IN query, no N+1."""
    ids = [e.id for e in entities]
    if not ids:
        return {}
    rows = db.execute(
        select(EntityTag.entity_id, Tag)
        .join(Tag, Tag.id == EntityTag.tag_id)
        .where(EntityTag.entity_id.in_(ids))
        .order_by(Tag.name)
    )
    out: dict[int, list[TagBrief]] = {}
    for entity_id, tag in rows:
        out.setdefault(entity_id, []).append(
            TagBrief(id=tag.id, name=tag.name, color=tag.color)
        )
    return out


def _out(
    entity: Entity,
    counts: dict[int, int],
    inbox_id: int | None,
    thumbs: dict[int, str] | None = None,
    tags: dict[int, list[TagBrief]] | None = None,
) -> EntityOut:
    thumb_path = (thumbs or {}).get(entity.cover_attachment_id)
    return EntityOut(
        id=entity.id,
        kind=entity.kind,
        subtype=entity.subtype,
        name=entity.name,
        description=entity.description,
        notes=entity.notes,
        parent_id=entity.parent_id,
        category_id=entity.category_id,
        depth=entity.depth,
        breadcrumb=entity.breadcrumb,
        asset_tag=entity.asset_tag,
        draft=entity.draft,
        archived=entity.archived_at is not None,
        protected=entity.id == inbox_id,
        child_count=counts.get(entity.id, 0),
        cover_attachment_id=entity.cover_attachment_id,
        thumb_url=f"/media/{thumb_path}" if thumb_path else None,
        tags=(tags or {}).get(entity.id, []),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        **{field: getattr(entity, field) for field in tree.INVENTORY_FIELDS},
    )


def _single_out(db: Session, entity: Entity) -> EntityOut:
    """_out with the per-entity batch maps — for single-entity responses."""
    return _out(
        entity,
        tree.child_counts(db, [entity.id]),
        tree.get_inbox_id(db),
        _thumb_map(db, [entity]),
        _tags_map(db, [entity]),
    )


@router.get("/tree", response_model=list[EntityOut])
async def get_tree(db: DbSession, include_archived: bool = False):
    entities = tree.list_tree(db, include_archived=include_archived)
    counts = tree.child_counts(db)
    inbox_id = tree.get_inbox_id(db)
    thumbs = _thumb_map(db, entities)
    tags = _tags_map(db, entities)
    return [_out(e, counts, inbox_id, thumbs, tags) for e in entities]


@router.post("", response_model=EntityOut, status_code=status.HTTP_201_CREATED)
async def create_entity(payload: EntityCreate, db: DbSession):
    with domain_errors():
        entity = tree.create_entity(
            db,
            name=payload.name,
            kind=payload.kind,
            parent_id=payload.parent_id,
            subtype=payload.subtype,
            description=payload.description,
            notes=payload.notes,
        )
    return _out(entity, {}, tree.get_inbox_id(db))


@router.get("/{entity_id}", response_model=EntityOut)
async def get_entity(entity_id: int, db: DbSession):
    with domain_errors():
        entity = tree.get_entity(db, entity_id)
    return _single_out(db, entity)


@router.get("/{entity_id}/children", response_model=list[EntityOut])
async def get_children(entity_id: int, db: DbSession, include_archived: bool = False):
    with domain_errors():
        children = tree.list_children(db, entity_id, include_archived=include_archived)
    counts = tree.child_counts(db, [c.id for c in children])
    inbox_id = tree.get_inbox_id(db)
    thumbs = _thumb_map(db, children)
    tags = _tags_map(db, children)
    return [_out(c, counts, inbox_id, thumbs, tags) for c in children]


@router.get("/{entity_id}/path", response_model=list[PathSegment])
async def get_path(entity_id: int, db: DbSession):
    with domain_errors():
        chain = tree.entity_path(db, entity_id)
    return [PathSegment(id=e.id, name=e.name, kind=e.kind) for e in chain]


@router.patch("/{entity_id}", response_model=EntityOut)
async def update_entity(entity_id: int, payload: EntityUpdate, db: DbSession):
    with domain_errors():
        entity = tree.update_entity(db, entity_id, payload.model_dump(exclude_unset=True))
    return _single_out(db, entity)


@router.post("/{entity_id}/move", response_model=EntityOut)
async def move_entity(entity_id: int, payload: MoveRequest, db: DbSession):
    with domain_errors():
        entity = tree.move_entity(db, entity_id, payload.parent_id)
    return _single_out(db, entity)


@router.post("/{entity_id}/duplicate", response_model=EntityOut, status_code=status.HTTP_201_CREATED)
async def duplicate_entity(entity_id: int, db: DbSession):
    with domain_errors():
        entity = metadata_svc.duplicate_entity(db, entity_id)
    return _single_out(db, entity)


@router.post("/{entity_id}/archive", response_model=EntityOut)
async def archive_entity(entity_id: int, db: DbSession):
    with domain_errors():
        entity = tree.archive_entity(db, entity_id)
    return _single_out(db, entity)


@router.post("/{entity_id}/unarchive", response_model=EntityOut)
async def unarchive_entity(entity_id: int, db: DbSession):
    with domain_errors():
        entity = tree.unarchive_entity(db, entity_id)
    return _single_out(db, entity)


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(entity_id: int, db: DbSession):
    with domain_errors():
        tree.delete_entity(db, entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
