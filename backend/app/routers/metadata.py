"""Metadata router: tags, categories, custom field defs/values, presets (M4).

Thin REST surface over app.services.metadata; entity-shaped responses reuse the
EntityOut helpers from app.routers.entities. Typed field-value coercion
failures map to 422 (InvalidValueError), on top of the usual 404/409.
"""

import json
from contextlib import contextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dependencies import DbSession, get_current_user
from app.routers.entities import EntityOut, _single_out
from app.services import metadata as svc
from app.services import tree

router = APIRouter(dependencies=[Depends(get_current_user)])

FieldType = Literal["text", "number", "date", "url"]


@contextmanager
def domain_errors():
    """Translate metadata/tree domain exceptions to HTTP errors."""
    try:
        yield
    except svc.InvalidValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )
    except tree.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except tree.RuleViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _non_blank(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("name must not be blank")
    return v


# --- tags ---------------------------------------------------------------------


class TagCreate(BaseModel):
    name: str = Field(min_length=1)
    color: str | None = None

    _name = field_validator("name")(_non_blank)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    color: str | None = None

    _name = field_validator("name")(_non_blank)


class TagOut(BaseModel):
    id: int
    name: str
    color: str | None
    usage_count: int


class EntityTagsPut(BaseModel):
    tags: list[str]


@router.get("/tags", response_model=list[TagOut])
async def list_tags(db: DbSession):
    return [
        TagOut(id=tag.id, name=tag.name, color=tag.color, usage_count=count)
        for tag, count in svc.list_tags(db)
    ]


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(payload: TagCreate, db: DbSession):
    with domain_errors():
        tag = svc.create_tag(db, payload.name, payload.color)
    return TagOut(id=tag.id, name=tag.name, color=tag.color, usage_count=0)


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag(tag_id: int, payload: TagUpdate, db: DbSession):
    with domain_errors():
        tag = svc.update_tag(db, tag_id, payload.model_dump(exclude_unset=True))
    usage = svc.tag_usage_count(db, tag.id)
    return TagOut(id=tag.id, name=tag.name, color=tag.color, usage_count=usage)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: int, db: DbSession):
    with domain_errors():
        svc.delete_tag(db, tag_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/entities/{entity_id}/tags", response_model=EntityOut)
async def set_entity_tags(entity_id: int, payload: EntityTagsPut, db: DbSession):
    with domain_errors():
        entity = svc.set_entity_tags(db, entity_id, payload.tags)
    return _single_out(db, entity)


# --- categories ---------------------------------------------------------------


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1)
    icon: str | None = None
    sort_order: int = 0

    _name = field_validator("name")(_non_blank)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    icon: str | None = None
    sort_order: int | None = None

    _name = field_validator("name")(_non_blank)

    @field_validator("sort_order")
    @classmethod
    def _not_null(cls, v: int | None) -> int:
        if v is None:
            raise ValueError("sort_order must be an integer, not null")
        return v


class FieldDefOut(BaseModel):
    id: int
    category_id: int | None
    name: str
    type: FieldType
    unit: str | None
    required: bool
    sort_order: int


class CategoryOut(BaseModel):
    id: int
    name: str
    icon: str | None
    sort_order: int
    fields: list[FieldDefOut] | None = None


def _fd_out(field_def) -> FieldDefOut:
    return FieldDefOut(
        id=field_def.id,
        category_id=field_def.category_id,
        name=field_def.name,
        type=field_def.type,
        unit=field_def.unit,
        required=field_def.required,
        sort_order=field_def.sort_order,
    )


def _cat_out(category, fields: list[FieldDefOut] | None = None) -> CategoryOut:
    return CategoryOut(
        id=category.id,
        name=category.name,
        icon=category.icon,
        sort_order=category.sort_order,
        fields=fields,
    )


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(db: DbSession, with_fields: bool = False):
    categories = svc.list_categories(db)
    if not with_fields:
        return [_cat_out(c) for c in categories]
    fields_map = svc.category_fields_map(db)
    return [
        _cat_out(c, [_fd_out(f) for f in fields_map.get(c.id, [])]) for c in categories
    ]


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(payload: CategoryCreate, db: DbSession):
    with domain_errors():
        category = svc.create_category(db, payload.name, payload.icon, payload.sort_order)
    return _cat_out(category)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(category_id: int, payload: CategoryUpdate, db: DbSession):
    with domain_errors():
        category = svc.update_category(
            db, category_id, payload.model_dump(exclude_unset=True)
        )
    return _cat_out(category)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: int, db: DbSession):
    with domain_errors():
        svc.delete_category(db, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- field defs ---------------------------------------------------------------


class FieldDefCreate(BaseModel):
    category_id: int | None = None
    name: str = Field(min_length=1)
    type: FieldType
    unit: str | None = None
    required: bool = False
    sort_order: int = 0

    _name = field_validator("name")(_non_blank)


class FieldDefUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    type: FieldType | None = None
    unit: str | None = None
    required: bool | None = None
    sort_order: int | None = None

    _name = field_validator("name")(_non_blank)

    @field_validator("type", "required", "sort_order")
    @classmethod
    def _not_null(cls, v):
        # Optional in the payload, but an explicit null would hit NOT NULL columns.
        if v is None:
            raise ValueError("field must not be null")
        return v


@router.get("/fields", response_model=list[FieldDefOut])
async def list_fields(
    db: DbSession, category_id: int | None = None, include_global: bool = True
):
    with domain_errors():
        defs = svc.list_field_defs(db, category_id=category_id, include_global=include_global)
    return [_fd_out(f) for f in defs]


@router.post("/fields", response_model=FieldDefOut, status_code=status.HTTP_201_CREATED)
async def create_field(payload: FieldDefCreate, db: DbSession):
    with domain_errors():
        field_def = svc.create_field_def(
            db,
            category_id=payload.category_id,
            name=payload.name,
            type=payload.type,
            unit=payload.unit,
            required=payload.required,
            sort_order=payload.sort_order,
        )
    return _fd_out(field_def)


@router.patch("/fields/{field_def_id}", response_model=FieldDefOut)
async def update_field(field_def_id: int, payload: FieldDefUpdate, db: DbSession):
    with domain_errors():
        field_def = svc.update_field_def(
            db, field_def_id, payload.model_dump(exclude_unset=True)
        )
    return _fd_out(field_def)


@router.delete("/fields/{field_def_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(field_def_id: int, db: DbSession):
    with domain_errors():
        svc.delete_field_def(db, field_def_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/fields/{field_def_id}/values", response_model=list[str])
async def field_value_suggestions(
    field_def_id: int,
    db: DbSession,
    q: str = "",
    limit: int = Query(default=20, ge=1, le=100),
):
    with domain_errors():
        return svc.autocomplete_values(db, field_def_id, q=q, limit=limit)


# --- field values -------------------------------------------------------------


class FieldValueIn(BaseModel):
    field_def_id: int
    value: str


class EntityFieldsPut(BaseModel):
    values: list[FieldValueIn]


class FieldValueOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    def_: FieldDefOut = Field(alias="def")
    value_text: str
    value_num: float | None
    value_date: str | None


def _fields_out(db, entity_id: int) -> list[FieldValueOut]:
    return [
        FieldValueOut(
            def_=_fd_out(field_def),
            value_text=value.value_text,
            value_num=value.value_num,
            value_date=value.value_date,
        )
        for field_def, value in svc.get_entity_fields(db, entity_id)
    ]


@router.get("/entities/{entity_id}/fields", response_model=list[FieldValueOut])
async def get_entity_fields(entity_id: int, db: DbSession):
    with domain_errors():
        return _fields_out(db, entity_id)


@router.put("/entities/{entity_id}/fields", response_model=list[FieldValueOut])
async def set_entity_fields(entity_id: int, payload: EntityFieldsPut, db: DbSession):
    with domain_errors():
        svc.set_entity_fields(
            db, entity_id, [v.model_dump() for v in payload.values]
        )
        return _fields_out(db, entity_id)


# --- presets ------------------------------------------------------------------


class PresetCreate(BaseModel):
    name: str = Field(min_length=1)
    payload: Any

    _name = field_validator("name")(_non_blank)


class PresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    payload: Any = None

    _name = field_validator("name")(_non_blank)


class PresetOut(BaseModel):
    id: int
    name: str
    payload: Any


def _preset_out(preset) -> PresetOut:
    return PresetOut(id=preset.id, name=preset.name, payload=json.loads(preset.payload))


@router.get("/presets", response_model=list[PresetOut])
async def list_presets(db: DbSession):
    return [_preset_out(p) for p in svc.list_presets(db)]


@router.post("/presets", response_model=PresetOut, status_code=status.HTTP_201_CREATED)
async def create_preset(payload: PresetCreate, db: DbSession):
    with domain_errors():
        preset = svc.create_preset(db, payload.name, json.dumps(payload.payload))
    return _preset_out(preset)


@router.patch("/presets/{preset_id}", response_model=PresetOut)
async def update_preset(preset_id: int, payload: PresetUpdate, db: DbSession):
    changes = payload.model_dump(exclude_unset=True)
    if "payload" in changes:
        changes["payload"] = json.dumps(changes["payload"])
    with domain_errors():
        preset = svc.update_preset(db, preset_id, changes)
    return _preset_out(preset)


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(preset_id: int, db: DbSession):
    with domain_errors():
        svc.delete_preset(db, preset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
