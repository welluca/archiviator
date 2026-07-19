"""Entities router: thin REST surface over app.services.tree (M2 containment tree)."""

from contextlib import contextmanager
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from app.dependencies import DbSession, get_current_user
from app.models.entity import Entity
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


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    subtype: str | None = None
    description: str | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _non_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class MoveRequest(BaseModel):
    parent_id: int | None


class EntityOut(BaseModel):
    id: int
    kind: str
    subtype: str | None
    name: str
    description: str | None
    notes: str | None
    parent_id: int | None
    depth: int
    breadcrumb: str
    asset_tag: str | None
    draft: bool
    archived: bool
    protected: bool
    child_count: int
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


def _out(entity: Entity, counts: dict[int, int], inbox_id: int | None) -> EntityOut:
    return EntityOut(
        id=entity.id,
        kind=entity.kind,
        subtype=entity.subtype,
        name=entity.name,
        description=entity.description,
        notes=entity.notes,
        parent_id=entity.parent_id,
        depth=entity.depth,
        breadcrumb=entity.breadcrumb,
        asset_tag=entity.asset_tag,
        draft=entity.draft,
        archived=entity.archived_at is not None,
        protected=entity.id == inbox_id,
        child_count=counts.get(entity.id, 0),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


@router.get("/tree", response_model=list[EntityOut])
async def get_tree(db: DbSession, include_archived: bool = False):
    entities = tree.list_tree(db, include_archived=include_archived)
    counts = tree.child_counts(db)
    inbox_id = tree.get_inbox_id(db)
    return [_out(e, counts, inbox_id) for e in entities]


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
    return _out(entity, tree.child_counts(db, [entity_id]), tree.get_inbox_id(db))


@router.get("/{entity_id}/children", response_model=list[EntityOut])
async def get_children(entity_id: int, db: DbSession, include_archived: bool = False):
    with domain_errors():
        children = tree.list_children(db, entity_id, include_archived=include_archived)
    counts = tree.child_counts(db, [c.id for c in children])
    inbox_id = tree.get_inbox_id(db)
    return [_out(c, counts, inbox_id) for c in children]


@router.get("/{entity_id}/path", response_model=list[PathSegment])
async def get_path(entity_id: int, db: DbSession):
    with domain_errors():
        chain = tree.entity_path(db, entity_id)
    return [PathSegment(id=e.id, name=e.name, kind=e.kind) for e in chain]


@router.patch("/{entity_id}", response_model=EntityOut)
async def update_entity(entity_id: int, payload: EntityUpdate, db: DbSession):
    with domain_errors():
        entity = tree.update_entity(db, entity_id, payload.model_dump(exclude_unset=True))
    return _out(entity, tree.child_counts(db, [entity_id]), tree.get_inbox_id(db))


@router.post("/{entity_id}/move", response_model=EntityOut)
async def move_entity(entity_id: int, payload: MoveRequest, db: DbSession):
    with domain_errors():
        entity = tree.move_entity(db, entity_id, payload.parent_id)
    return _out(entity, tree.child_counts(db, [entity_id]), tree.get_inbox_id(db))


@router.post("/{entity_id}/archive", response_model=EntityOut)
async def archive_entity(entity_id: int, db: DbSession):
    with domain_errors():
        entity = tree.archive_entity(db, entity_id)
    return _out(entity, tree.child_counts(db, [entity_id]), tree.get_inbox_id(db))


@router.post("/{entity_id}/unarchive", response_model=EntityOut)
async def unarchive_entity(entity_id: int, db: DbSession):
    with domain_errors():
        entity = tree.unarchive_entity(db, entity_id)
    return _out(entity, tree.child_counts(db, [entity_id]), tree.get_inbox_id(db))


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(entity_id: int, db: DbSession):
    with domain_errors():
        tree.delete_entity(db, entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
