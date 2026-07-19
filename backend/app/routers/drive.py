"""Drive router (M9): connection lifecycle, config, browse, scan inbox,
thumbnails, reconciliation and backup push. Thin REST surface over
app.services.drive; NotFoundError -> 404, RuleViolation -> 409.

Endpoints that hit the Drive API are plain def so FastAPI runs them in the
threadpool (network calls must not block the event loop)."""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import DbSession, get_current_user
from app.models.attachment import Attachment
from app.models.drive import ScanInbox
from app.models.entity import Entity
from app.routers.attachments import AttachmentOut, _att_out, _cover_id
from app.services import drive as drive_svc
from app.services.tree import NotFoundError, RuleViolation

router = APIRouter(dependencies=[Depends(get_current_user)])


@contextmanager
def domain_errors():
    try:
        yield
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuleViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# --- schemas ------------------------------------------------------------------


class ScansFolderOut(BaseModel):
    id: str
    name: str | None


class InboxCounts(BaseModel):
    new: int
    attached: int
    ignored: int


class DriveStatusOut(BaseModel):
    configured: bool
    connected: bool
    connect_pending: bool
    email: str | None
    scans_folder: ScansFolderOut | None
    poll_interval_min: int
    backup_upload_enabled: bool
    last_poll_at: str | None
    last_backup_upload_at: str | None
    inbox_counts: InboxCounts


class DriveConfigIn(BaseModel):
    credentials_path: str | None = None
    scans_folder_id: str | None = None
    scans_folder_name: str | None = None
    poll_interval_min: int | None = Field(default=None, ge=5, le=1440)
    backup_upload_enabled: bool | None = None


class ConnectOut(BaseModel):
    status: Literal["pending"]
    message: str


class BrowseFolder(BaseModel):
    id: str
    name: str


class BrowseFile(BaseModel):
    id: str
    name: str
    mime: str | None
    modified_time: str | None
    size: int | None


class BrowseOut(BaseModel):
    folders: list[BrowseFolder]
    files: list[BrowseFile]


class ScanNowOut(BaseModel):
    new: int
    seen: int


class ScanRowOut(BaseModel):
    id: int
    drive_file_id: str
    name: str
    mime: str | None
    modified_time: str | None
    md5: str | None
    size_bytes: int | None
    discovered_at: datetime
    status: Literal["new", "attached", "ignored"]
    attachment_id: int | None
    thumbnail_url: str | None
    # Present on ATTACHED rows (attachment -> entity join) so the frontend's
    # attached tab can link straight to the entry.
    entity_id: int | None = None
    entity_name: str | None = None


class InboxAttachIn(BaseModel):
    entity_id: int
    title: str | None = None


class InboxAttachOut(BaseModel):
    row: ScanRowOut
    attachment: AttachmentOut


class ThumbnailOut(BaseModel):
    url: str | None


class ReconcileOut(BaseModel):
    ok: int
    missing: int
    changed: int


class DriveBackupOut(BaseModel):
    file: str
    drive_file_id: str


def _row_out(row: ScanInbox, entity: tuple[int, str] | None = None) -> ScanRowOut:
    return ScanRowOut(
        id=row.id,
        drive_file_id=row.drive_file_id,
        name=row.name,
        mime=row.mime,
        modified_time=row.modified_time,
        md5=row.md5,
        size_bytes=row.size_bytes,
        # Stored naive-UTC; serialize timezone-AWARE so the frontend's
        # `new Date()` parses it as UTC (same pattern as backup.list_backups).
        discovered_at=row.discovered_at.replace(tzinfo=timezone.utc),
        status=row.status,
        attachment_id=row.attachment_id,
        thumbnail_url=drive_svc.cached_thumb_url(row.drive_file_id),
        entity_id=entity[0] if entity else None,
        entity_name=entity[1] if entity else None,
    )


def _attached_entities(db, rows: list[ScanInbox]) -> dict[int, tuple[int, str]]:
    """attachment_id -> (entity_id, entity_name) for rows that link to an
    attachment — one batched query, no per-row lookups."""
    ids = [r.attachment_id for r in rows if r.attachment_id is not None]
    if not ids:
        return {}
    return {
        att_id: (ent_id, ent_name)
        for att_id, ent_id, ent_name in db.execute(
            select(Attachment.id, Entity.id, Entity.name)
            .join(Entity, Attachment.entity_id == Entity.id)
            .where(Attachment.id.in_(ids))
        )
    }


# --- status / config / connect ------------------------------------------------


@router.get("/status", response_model=DriveStatusOut)
async def drive_status(db: DbSession):
    return drive_svc.get_status(db)


@router.put("/config", response_model=DriveStatusOut)
async def update_config(payload: DriveConfigIn, db: DbSession, request: Request):
    changes = payload.model_dump(exclude_unset=True)
    with domain_errors():
        drive_svc.update_config(db, changes)
    # Live-reschedule the poll job when a scheduler is running; with the
    # scheduler disabled the new interval applies on the next service restart.
    if changes.get("poll_interval_min") is not None:
        scheduler = getattr(request.app.state, "scheduler", None)
        drive_svc.reschedule_poll(scheduler, changes["poll_interval_min"])
    return drive_svc.get_status(db)


@router.post("/connect", response_model=ConnectOut, status_code=status.HTTP_202_ACCEPTED)
async def connect(db: DbSession):
    with domain_errors():
        drive_svc.start_connect(db)
    return ConnectOut(
        status="pending",
        message=(
            "Google sign-in started: a browser window is opening ON THE SERVER PC "
            "(this machine). Complete the consent there, then poll /drive/status "
            "until connected. Note: the OAuth consent screen must be 'In production' "
            "— tokens from a client 'In testing' expire after 7 days."
        ),
    )


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(db: DbSession):
    drive_svc.disconnect(db)


# --- browse / scan / inbox ----------------------------------------------------


@router.get("/browse", response_model=BrowseOut)
def browse(db: DbSession, folder_id: str = Query(default="root")):
    with domain_errors():
        return drive_svc.browse(db, folder_id)


@router.post("/scan-now", response_model=ScanNowOut)
def scan_now(db: DbSession):
    with domain_errors():
        return drive_svc.scan_once(db)


@router.get("/inbox", response_model=list[ScanRowOut])
async def list_inbox(
    db: DbSession,
    status_filter: Literal["new", "attached", "ignored"] | None = Query(
        default=None, alias="status"
    ),
):
    rows = drive_svc.list_inbox(db, status_filter)
    entities = _attached_entities(db, rows)
    return [_row_out(row, entities.get(row.attachment_id)) for row in rows]


@router.post("/inbox/{row_id}/ignore", response_model=ScanRowOut)
async def ignore_inbox_row(row_id: int, db: DbSession):
    with domain_errors():
        return _row_out(drive_svc.ignore_row(db, row_id))


@router.post("/inbox/{row_id}/attach", response_model=InboxAttachOut)
async def attach_inbox_row(row_id: int, payload: InboxAttachIn, db: DbSession):
    with domain_errors():
        row, attachment = drive_svc.attach_inbox_row(
            db, row_id, payload.entity_id, title=payload.title
        )
    entity = db.get(Entity, attachment.entity_id)
    return InboxAttachOut(
        row=_row_out(row, (entity.id, entity.name) if entity else None),
        attachment=_att_out(attachment, _cover_id(db, attachment.entity_id)),
    )


# --- thumbnails / reconcile / backup ------------------------------------------


@router.post("/thumbnail/{file_id}", response_model=ThumbnailOut)
def ensure_thumbnail(file_id: str, db: DbSession):
    with domain_errors():
        return drive_svc.ensure_thumbnail(db, file_id)


@router.post("/reconcile", response_model=ReconcileOut)
def reconcile(db: DbSession):
    with domain_errors():
        return drive_svc.reconcile(db)


@router.post("/backup-now", response_model=DriveBackupOut)
def backup_now(db: DbSession):
    with domain_errors():
        return drive_svc.backup_now(db)
