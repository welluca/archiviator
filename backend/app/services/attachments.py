"""Attachment service: upload pipeline orchestration, listing, metadata, cover.

Domain errors reuse tree.NotFoundError / tree.RuleViolation (404 / 409) plus the
media errors (413 / 415); routers translate. Dedup: a re-upload of identical
processed bytes reuses the on-disk files but always creates a NEW attachment row.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attachment import Attachment
from app.models.entity import Entity
from app.services import media
from app.services.tree import NotFoundError, RuleViolation

PDF_MAGIC = b"%PDF-"


def _get_entity(db: Session, entity_id: int) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError(f"Entity {entity_id} not found")
    return entity


def _get_attachment(db: Session, attachment_id: int) -> Attachment:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise NotFoundError(f"Attachment {attachment_id} not found")
    return attachment


def process_upload(db: Session, data: bytes, title: str | None = None) -> Attachment:
    """Infer type from content, run the media pipeline (413/415 happen HERE,
    before any row exists) and build an Attachment row that is NOT yet added to
    the session — entity_id unset, caller wires it and commits (intake capture
    reuses this inside its single transaction). MAX_UPLOAD is read at call time
    so tests can patch it."""
    if len(data) > media.MAX_UPLOAD:
        raise media.FileTooLargeError(
            f"Upload exceeds the {media.MAX_UPLOAD // (1024 * 1024)} MB limit"
        )

    # The PDF spec tolerates the header anywhere in the first 1024 bytes
    # (BOM or junk prefixes occur in the wild).
    if PDF_MAGIC in data[:1024]:
        processed = media.process_document(data)
        attachment = Attachment(
            type="document",
            title=title,
            file_path=processed.file_path,
            mime=processed.mime,
            byte_size=processed.byte_size,
            content_hash=processed.content_hash,
        )
    else:
        photo = media.process_photo(data)  # raises UnsupportedMediaError -> 415
        attachment = Attachment(
            type="photo",
            title=title,
            file_path=photo.file_path,
            display_path=photo.display_path,
            thumb_path=photo.thumb_path,
            mime=photo.mime,
            byte_size=photo.byte_size,
            content_hash=photo.content_hash,
            width=photo.width,
            height=photo.height,
        )

    # Dedup: same processed bytes -> same files reused, metadata copied from the
    # existing row (still a brand-new attachment row).
    existing = db.scalars(
        select(Attachment)
        .where(Attachment.content_hash == attachment.content_hash)
        .limit(1)
    ).first()
    if existing is not None:
        attachment.byte_size = existing.byte_size
        attachment.width = existing.width
        attachment.height = existing.height
        if attachment.type == "photo":
            media.ensure_derivatives(attachment.content_hash)
    return attachment


def create_attachment(
    db: Session, entity_id: int, data: bytes, title: str | None = None
) -> Attachment:
    """Pipeline + insert a row (allowed on every entity kind)."""
    _get_entity(db, entity_id)
    attachment = process_upload(db, data, title=title)
    attachment.entity_id = entity_id
    db.add(attachment)
    db.commit()
    return attachment


def list_for_entity(db: Session, entity_id: int) -> list[Attachment]:
    _get_entity(db, entity_id)
    stmt = (
        select(Attachment)
        .where(Attachment.entity_id == entity_id)
        .order_by(Attachment.sort_order, Attachment.created_at, Attachment.id)
    )
    return list(db.scalars(stmt))


def update_meta(db: Session, attachment_id: int, changes: dict) -> Attachment:
    attachment = _get_attachment(db, attachment_id)
    for field in ("title", "sort_order"):
        if field in changes:
            setattr(attachment, field, changes[field])
    db.commit()
    return attachment


def delete_attachment(db: Session, attachment_id: int) -> None:
    """Delete the row; unlink files only if no other row shares the content hash.
    If it was the owning entity's cover, the cover clears. drive_link rows also
    drop their cached Drive thumbnails (best-effort — the cache is regenerable,
    same tradeoff as the media unlinks)."""
    attachment = _get_attachment(db, attachment_id)
    entity = db.get(Entity, attachment.entity_id)
    if entity is not None and entity.cover_attachment_id == attachment.id:
        entity.cover_attachment_id = None
    content_hash = attachment.content_hash
    drive_file_id = attachment.drive_file_id if attachment.type == "drive_link" else None
    db.delete(attachment)
    db.commit()
    media.delete_files_if_unreferenced(db, content_hash, exclude_attachment_id=attachment_id)
    if drive_file_id:
        from app.services import drive as drive_svc

        try:
            drive_svc.delete_cached_thumbs(drive_file_id)
        except OSError:
            pass


def set_cover(db: Session, entity_id: int, attachment_id: int | None) -> Entity:
    """Set (or clear, with None) the entity's cover; only its own photos qualify."""
    entity = _get_entity(db, entity_id)
    if attachment_id is None:
        entity.cover_attachment_id = None
        db.commit()
        return entity

    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.entity_id != entity.id:
        raise RuleViolation("Cover must be an attachment of this entity")
    if attachment.type != "photo":
        raise RuleViolation("Cover must be a photo attachment")
    entity.cover_attachment_id = attachment.id
    db.commit()
    return entity
