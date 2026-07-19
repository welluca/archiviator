"""Intake router (M7): one-shot capture, drafts listing, batch promote.

POST /intake/capture accepts JWT OR capture-scope device tokens
(get_capture_actor) so iOS Shortcuts can post photos without a session;
drafts and promote are JWT-only like the rest of the API.
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field

from app.dependencies import DbSession, get_capture_actor, get_current_user
from app.routers.attachments import AttachmentOut, _att_out, domain_errors
from app.routers.entities import EntityOut, _out, _single_out, _tags_map, _thumb_map
from app.services import intake as svc
from app.services import media, tree

router = APIRouter(dependencies=[Depends(get_current_user)])
capture_router = APIRouter(dependencies=[Depends(get_capture_actor)])


class CaptureOut(BaseModel):
    entity: EntityOut
    attachment: AttachmentOut


class PromoteRequest(BaseModel):
    entity_ids: list[int] = Field(min_length=1)
    parent_id: int | None = None  # None (or omitted) = no move
    category_id: int | None = None  # omitted = no change; explicit null clears
    tags: list[str] | None = None  # omitted = no change; a list REPLACES
    clear_draft: bool = True


class PromoteError(BaseModel):
    entity_id: int
    message: str


class PromoteResult(BaseModel):
    promoted: list[EntityOut]
    errors: list[PromoteError]


@capture_router.post(
    "/intake/capture", response_model=CaptureOut, status_code=status.HTTP_201_CREATED
)
async def capture(
    db: DbSession,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    note: str | None = Form(default=None),
):
    """ONE round trip: draft item in the Inbox + photo attached + cover set."""
    # Read at most MAX_UPLOAD + 1 bytes: one byte over the cap is proof enough for 413.
    data = await file.read(media.MAX_UPLOAD + 1)
    with domain_errors():
        entity, attachment = svc.capture(db, data, name=name, note=note)
    return CaptureOut(
        entity=_single_out(db, entity),
        attachment=_att_out(attachment, entity.cover_attachment_id),
    )


@router.get("/intake/drafts", response_model=list[EntityOut])
async def list_drafts(db: DbSession):
    drafts = svc.list_drafts(db)
    counts = tree.child_counts(db, [d.id for d in drafts])
    inbox_id = tree.get_inbox_id(db)
    thumbs = _thumb_map(db, drafts)
    tags = _tags_map(db, drafts)
    return [_out(d, counts, inbox_id, thumbs, tags) for d in drafts]


@router.post("/intake/promote", response_model=PromoteResult)
async def promote(payload: PromoteRequest, db: DbSession):
    with domain_errors():
        promoted, errors = svc.promote(
            db,
            payload.entity_ids,
            parent_id=payload.parent_id,
            category_id=payload.category_id,
            set_category="category_id" in payload.model_fields_set,
            tags=payload.tags,
            clear_draft=payload.clear_draft,
        )
    counts = tree.child_counts(db, [e.id for e in promoted])
    inbox_id = tree.get_inbox_id(db)
    thumbs = _thumb_map(db, promoted)
    tags = _tags_map(db, promoted)
    return PromoteResult(
        promoted=[_out(e, counts, inbox_id, thumbs, tags) for e in promoted],
        errors=[PromoteError(**e) for e in errors],
    )
