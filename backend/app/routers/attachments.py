"""Attachments router: uploads, listing, metadata, delete, entity cover.

Thin REST surface over app.services.attachments; media URLs are built from the
stored relative paths as '/media/attachments/…' and '/media/derived/…'.
"""

from contextlib import contextmanager
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, field_validator

from app.dependencies import DbSession, get_capture_actor, get_current_user
from app.models.attachment import Attachment
from app.models.entity import Entity
from app.routers.entities import EntityOut, _single_out
from app.services import attachments as svc
from app.services import media, tree

router = APIRouter(dependencies=[Depends(get_current_user)])
# The upload endpoint ALSO accepts capture-scope device tokens (M7 phone
# capture adds photos to existing entities); every other attachment endpoint
# stays JWT-only on the router above.
capture_router = APIRouter(dependencies=[Depends(get_capture_actor)])


class AttachmentOut(BaseModel):
    id: int
    entity_id: int
    type: Literal["photo", "document", "drive_link"]
    title: str | None
    sort_order: int
    # Optional since M9: drive_link rows may lack a mime/size (Google Docs
    # report no size); stored photo/document rows always carry both.
    mime: str | None
    byte_size: int | None
    width: int | None
    height: int | None
    is_cover: bool
    urls: dict[str, str]
    # M9: 'ok' | 'missing' | 'changed' for drive_link rows, None otherwise.
    drive_status: str | None = None
    # M9: Drive id + denormalized file name for drive_link rows (the frontend
    # renders drive_name and keys thumbnails by drive_file_id); None otherwise.
    drive_file_id: str | None = None
    drive_name: str | None = None
    created_at: datetime


class DriveAttachIn(BaseModel):
    file_id: str
    title: str | None = None


class AttachmentUpdate(BaseModel):
    title: str | None = None
    sort_order: int | None = None

    @field_validator("sort_order")
    @classmethod
    def _not_null(cls, v: int | None) -> int:
        # Optional in the payload, but an explicit null would hit the NOT NULL column.
        if v is None:
            raise ValueError("sort_order must be an integer, not null")
        return v


class CoverRequest(BaseModel):
    attachment_id: int | None


@contextmanager
def domain_errors():
    """Translate attachment/media domain exceptions to HTTP errors."""
    try:
        yield
    except tree.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except tree.RuleViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except media.FileTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    except media.UnsupportedMediaError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        )


def _att_out(attachment: Attachment, cover_attachment_id: int | None) -> AttachmentOut:
    if attachment.type == "drive_link":
        # No stored file: open-in-Drive link + the cached thumbnail when the
        # /drive/thumbnail ensure endpoint has populated drive-cache/.
        from app.services import drive as drive_svc

        urls = {"open": f"https://drive.google.com/file/d/{attachment.drive_file_id}/view"}
        thumb = drive_svc.cached_thumb_url(attachment.drive_file_id)
        if thumb:
            urls["thumb"] = thumb
    else:
        urls = {"original": f"/media/{attachment.file_path}"}
        if attachment.display_path:
            urls["display"] = f"/media/{attachment.display_path}"
        if attachment.thumb_path:
            urls["thumb"] = f"/media/{attachment.thumb_path}"
    return AttachmentOut(
        id=attachment.id,
        entity_id=attachment.entity_id,
        type=attachment.type,
        title=attachment.title,
        sort_order=attachment.sort_order,
        mime=attachment.mime,
        byte_size=attachment.byte_size,
        width=attachment.width,
        height=attachment.height,
        is_cover=attachment.id == cover_attachment_id,
        urls=urls,
        drive_status=attachment.drive_status if attachment.type == "drive_link" else None,
        drive_file_id=attachment.drive_file_id if attachment.type == "drive_link" else None,
        drive_name=attachment.drive_name if attachment.type == "drive_link" else None,
        created_at=attachment.created_at,
    )


def _cover_id(db, entity_id: int) -> int | None:
    entity = db.get(Entity, entity_id)
    return entity.cover_attachment_id if entity else None


@capture_router.post(
    "/entities/{entity_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    entity_id: int,
    db: DbSession,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
):
    # Read at most MAX_UPLOAD + 1 bytes: one byte over the cap is proof enough for 413.
    data = await file.read(media.MAX_UPLOAD + 1)
    with domain_errors():
        attachment = svc.create_attachment(db, entity_id, data, title=title)
    return _att_out(attachment, _cover_id(db, entity_id))


@router.post(
    "/entities/{entity_id}/attachments/drive",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
def attach_drive_file(entity_id: int, payload: DriveAttachIn, db: DbSession):
    """M9: attach ANY Drive file (picked via /drive/browse) as a drive_link.
    Plain def — the metadata fetch is a network call (threadpool)."""
    from app.services import drive as drive_svc

    with domain_errors():
        attachment = drive_svc.attach_file(
            db, entity_id, payload.file_id, title=payload.title
        )
    return _att_out(attachment, _cover_id(db, entity_id))


@router.get("/entities/{entity_id}/attachments", response_model=list[AttachmentOut])
async def list_attachments(entity_id: int, db: DbSession):
    with domain_errors():
        rows = svc.list_for_entity(db, entity_id)
    cover_id = _cover_id(db, entity_id)
    return [_att_out(a, cover_id) for a in rows]


@router.patch("/attachments/{attachment_id}", response_model=AttachmentOut)
async def update_attachment(attachment_id: int, payload: AttachmentUpdate, db: DbSession):
    with domain_errors():
        attachment = svc.update_meta(
            db, attachment_id, payload.model_dump(exclude_unset=True)
        )
    return _att_out(attachment, _cover_id(db, attachment.entity_id))


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(attachment_id: int, db: DbSession):
    with domain_errors():
        svc.delete_attachment(db, attachment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/entities/{entity_id}/cover", response_model=EntityOut)
async def set_cover(entity_id: int, payload: CoverRequest, db: DbSession):
    with domain_errors():
        entity = svc.set_cover(db, entity_id, payload.attachment_id)
    return _single_out(db, entity)
