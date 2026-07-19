"""Labels router (M5): tag resolution, claim/void, entity asset-tag assignment,
label templates and printed batches with PDF download.

Thin REST surface over app.services.labels. Tag normalization (trim +
uppercase) happens in the service at every entry point, so /a/{tag} scans are
case-insensitive. The batch PDF is served with Bearer auth (FileResponse) —
the frontend downloads it via an axios blob + object URL, never a query-param
token. asset_tag writes go through ORM updates on entity, so the search_fts
entity AU trigger (AFTER UPDATE OF ... asset_tag) keeps search in sync.
"""

from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import get_settings
from app.dependencies import Actor, DbSession, get_capture_actor, get_current_user
from app.models.labels import LabelTemplate
from app.routers.entities import EntityOut, _single_out, _thumb_map
from app.services import labels as svc
from app.services import tree

router = APIRouter(dependencies=[Depends(get_current_user)])
# /labels/resolve also serves the phone capture flow (QR scan -> where am I),
# so it accepts capture-scope device tokens (M7); everything else stays
# JWT-only on the router above.
capture_router = APIRouter(dependencies=[Depends(get_capture_actor)])

Kind = Literal["space", "furniture", "container", "item"]


@contextmanager
def domain_errors():
    """Translate tree/labels domain exceptions to HTTP errors."""
    try:
        yield
    except tree.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except tree.RuleViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# --- schemas ------------------------------------------------------------------


class ConfigOut(BaseModel):
    base_url: str


class TemplateOut(BaseModel):
    id: int
    name: str
    page_w_mm: float
    page_h_mm: float
    cols: int
    rows: int
    label_w_mm: float
    label_h_mm: float
    margin_top_mm: float
    margin_left_mm: float
    gutter_x_mm: float
    gutter_y_mm: float
    qr_size_mm: float
    show_name: bool
    show_breadcrumb: bool


class LabelOut(BaseModel):
    id: int
    batch_id: int
    asset_tag: str
    status: Literal["unclaimed", "claimed", "void"]
    entity_id: int | None
    entity_name: str | None = None
    claimed_at: datetime | None


class ClaimCreate(BaseModel):
    name: str = Field(min_length=1)
    kind: Kind
    parent_id: int | None = None
    subtype: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class ClaimRequest(BaseModel):
    entity_id: int | None = None
    create: ClaimCreate | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.entity_id is None) == (self.create is None):
            raise ValueError("provide exactly one of entity_id or create")
        return self


class AssetTagRequest(BaseModel):
    """{auto:true} | {tag:"..."} | {tag:null} — an explicit choice is required
    so an accidental empty payload can never clear a tag."""

    auto: bool = False
    tag: str | None = None

    @model_validator(mode="after")
    def _explicit(self):
        if self.auto and self.tag is not None:
            raise ValueError("provide either auto or tag, not both")
        if not self.auto and "tag" not in self.model_fields_set:
            raise ValueError("provide auto:true, tag:\"...\" or tag:null")
        return self


class BatchCreate(BaseModel):
    template_id: int
    count: int | None = Field(default=None, ge=1, le=5000)
    entity_ids: list[int] | None = None
    skip_first: int = Field(default=0, ge=0)
    note: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.count is None) == (self.entity_ids is None):
            raise ValueError("provide exactly one of count or entity_ids")
        if self.entity_ids is not None and not self.entity_ids:
            raise ValueError("entity_ids must not be empty")
        return self


class BatchOut(BaseModel):
    id: int
    note: str | None
    created_at: datetime
    pdf_url: str
    label_count: int
    template: TemplateOut
    labels: list[LabelOut]


class BatchSummaryOut(BaseModel):
    id: int
    note: str | None
    created_at: datetime
    pdf_url: str
    label_count: int
    template: TemplateOut
    counts: dict[Literal["unclaimed", "claimed", "void"], int]


def _template_out(template) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        name=template.name,
        page_w_mm=template.page_w_mm,
        page_h_mm=template.page_h_mm,
        cols=template.cols,
        rows=template.rows,
        label_w_mm=template.label_w_mm,
        label_h_mm=template.label_h_mm,
        margin_top_mm=template.margin_top_mm,
        margin_left_mm=template.margin_left_mm,
        gutter_x_mm=template.gutter_x_mm,
        gutter_y_mm=template.gutter_y_mm,
        qr_size_mm=template.qr_size_mm,
        show_name=template.show_name,
        show_breadcrumb=template.show_breadcrumb,
    )


def _label_out(label, entity_name: str | None = None) -> LabelOut:
    return LabelOut(
        id=label.id,
        batch_id=label.batch_id,
        asset_tag=label.asset_tag,
        status=label.status,
        entity_id=label.entity_id,
        entity_name=entity_name,
        claimed_at=label.claimed_at,
    )


def _pdf_url(batch_id: int) -> str:
    return f"/api/v1/labels/batches/{batch_id}/pdf"


def _batch_out(db, batch) -> BatchOut:
    rows = svc.batch_labels(db, batch.id)
    template = db.get(LabelTemplate, batch.template_id)
    return BatchOut(
        id=batch.id,
        note=batch.note,
        created_at=batch.created_at,
        pdf_url=_pdf_url(batch.id),
        label_count=len(rows),
        template=_template_out(template),
        labels=[_label_out(label, name) for label, name in rows],
    )


# --- config & templates -------------------------------------------------------


@router.get("/labels/config", response_model=ConfigOut)
async def get_config(db: DbSession):
    """QR payload host for client-side previews (meta row, never hardcoded)."""
    return ConfigOut(base_url=svc.get_base_url(db))


@router.get("/labels/templates", response_model=list[TemplateOut])
async def list_templates(db: DbSession):
    return [_template_out(t) for t in svc.list_templates(db)]


# --- resolve / claim / void ---------------------------------------------------


def _slim_entity(db, entity) -> dict:
    """The device-token view of a resolved entity: enough for 'where am I /
    what is this' on a phone, nothing more. A leaked capture token must never
    read purchase prices, serials or notes — those stay JWT-only (EntityOut)."""
    thumb_path = _thumb_map(db, [entity]).get(entity.cover_attachment_id)
    return {
        "id": entity.id,
        "name": entity.name,
        "kind": entity.kind,
        "breadcrumb": entity.breadcrumb,
        "asset_tag": entity.asset_tag,
        "thumb_url": f"/media/{thumb_path}" if thumb_path else None,
    }


@capture_router.get("/labels/resolve/{tag}")
async def resolve_tag(
    tag: str, db: DbSession, actor: Annotated[Actor, Depends(get_capture_actor)]
):
    """{"status":"entity","entity":EntityOut} | {"status":"unclaimed","label":{...}}.
    Exact union shape (no null side-keys), hence no single response_model.
    Device-token callers get a slimmed entity instead of the full EntityOut."""
    with domain_errors():
        kind, obj = svc.resolve(db, tag)
    if kind == "entity":
        entity = _slim_entity(db, obj) if actor.via_device_token else _single_out(db, obj)
        return {"status": "entity", "entity": entity}
    return {"status": "unclaimed", "label": {"asset_tag": obj.asset_tag, "batch_id": obj.batch_id}}


@router.post("/labels/{tag}/claim", response_model=EntityOut)
async def claim_label(tag: str, payload: ClaimRequest, db: DbSession):
    with domain_errors():
        entity = svc.claim(
            db,
            tag,
            entity_id=payload.entity_id,
            create=payload.create.model_dump() if payload.create else None,
        )
    return _single_out(db, entity)


@router.post("/labels/{tag}/void", response_model=LabelOut)
async def void_label(tag: str, db: DbSession):
    with domain_errors():
        label = svc.void(db, tag)
    return _label_out(label)


# --- entity asset-tag ---------------------------------------------------------


@router.post("/entities/{entity_id}/asset-tag", response_model=EntityOut)
async def set_asset_tag(entity_id: int, payload: AssetTagRequest, db: DbSession):
    with domain_errors():
        entity = svc.assign_asset_tag(db, entity_id, tag=payload.tag, auto=payload.auto)
    return _single_out(db, entity)


# --- batches ------------------------------------------------------------------


@router.post("/labels/batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
async def create_batch(payload: BatchCreate, db: DbSession):
    with domain_errors():
        batch, rendered_tags = svc.create_batch(
            db,
            template_id=payload.template_id,
            count=payload.count,
            entity_ids=payload.entity_ids,
            skip_first=payload.skip_first,
            note=payload.note,
        )
    # Report what was RENDERED (mode 2 reprints can include labels owned by
    # earlier batches), not just this batch's own rows.
    rows = svc.labels_by_tags(db, rendered_tags)
    template = db.get(LabelTemplate, batch.template_id)
    return BatchOut(
        id=batch.id,
        note=batch.note,
        created_at=batch.created_at,
        pdf_url=_pdf_url(batch.id),
        label_count=len(rows),
        template=_template_out(template),
        labels=[_label_out(label, name) for label, name in rows],
    )


@router.get("/labels/batches", response_model=list[BatchSummaryOut])
async def list_batches(db: DbSession):
    batches = svc.list_batches(db)
    counts = svc.batch_status_counts(db, [b.id for b in batches])
    templates = {t.id: _template_out(t) for t in svc.list_templates(db)}
    out = []
    for batch in batches:
        batch_counts = counts.get(batch.id, {"unclaimed": 0, "claimed": 0, "void": 0})
        out.append(
            BatchSummaryOut(
                id=batch.id,
                note=batch.note,
                created_at=batch.created_at,
                pdf_url=_pdf_url(batch.id),
                label_count=sum(batch_counts.values()),
                template=templates[batch.template_id],
                counts=batch_counts,
            )
        )
    return out


@router.get("/labels/batches/{batch_id}", response_model=BatchOut)
async def get_batch(batch_id: int, db: DbSession):
    with domain_errors():
        batch = svc.get_batch(db, batch_id)
    return _batch_out(db, batch)


@router.get("/labels/batches/{batch_id}/pdf")
async def get_batch_pdf(batch_id: int, db: DbSession):
    with domain_errors():
        batch = svc.get_batch(db, batch_id)
    if not batch.pdf_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch has no PDF")
    path = get_settings().data_dir / batch.pdf_path
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF file is missing")
    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=f"labels-batch-{batch.id:04d}.pdf",
    )
