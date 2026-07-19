"""Intake service (M7): the <30s capture loop and the desktop triage promote.

capture() is ONE round trip and ONE transaction: the media pipeline runs first
(any 413/415 fires before a single row exists), then draft entity in the Inbox
+ attachment + cover land in a single commit.

promote() mirrors the CSV importer's shape: every entity runs under a SAVEPOINT
so one failure (containment, unknown id, protected Inbox) rolls back alone —
each successful entity is fully applied or the failed one fully untouched
(tags included) — and the whole batch commits once at the end.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.attachment import Attachment
from app.models.entity import Entity
from app.models.metadata import Category
from app.services import attachments as attachments_svc
from app.services import media
from app.services import metadata as metadata_svc
from app.services import tree
from app.services.tree import NotFoundError, RuleViolation, TreeError


def capture(
    db: Session, data: bytes, name: str | None = None, note: str | None = None
) -> tuple[Entity, Attachment]:
    """One shot from the phone: draft item in the Inbox root with the photo
    attached and set as cover. Name defaults to 'Capture YYYY-MM-DD HH:MM:SS'
    (local server time)."""
    # Capture is photos-only: a PDF would pass the attachment pipeline as a
    # document but can never be a cover.
    if attachments_svc.PDF_MAGIC in data[:1024]:
        raise media.UnsupportedMediaError("Capture accepts photos only")
    attachment = attachments_svc.process_upload(db, data)  # 413/415 before any row

    try:
        inbox_id = tree.get_inbox_id(db)
        if inbox_id is None:  # unreachable after migration 0002, but never guess a parent
            raise NotFoundError("Inbox root is missing")
        if name is None or not name.strip():
            name = f"Capture {datetime.now():%Y-%m-%d %H:%M:%S}"

        entity = tree.create_entity(
            db, name=name, kind="item", parent_id=inbox_id, notes=note, commit=False
        )
        entity.draft = True
        attachment.entity_id = entity.id
        db.add(attachment)
        db.flush()
        entity.cover_attachment_id = attachment.id
        db.commit()
    except Exception:
        # process_upload already wrote content-addressed files; with no row
        # committed they would be orphans. Roll back, then let the refcounted
        # cleanup unlink whatever no attachment row references (a dedup'd
        # pre-existing row keeps the files alive).
        db.rollback()
        media.delete_files_if_unreferenced(db, attachment.content_hash)
        raise
    return entity, attachment


def list_drafts(db: Session) -> list[Entity]:
    """ALL draft entities wherever they live, newest first — except inside
    archived subtrees (same shared predicate as tree listing / search, so a
    draft in an archived box is hidden everywhere at once)."""
    stmt = (
        select(Entity)
        .where(Entity.draft.is_(True), tree.not_in_archived_subtree())
        .order_by(Entity.created_at.desc(), Entity.id.desc())
    )
    return list(db.scalars(stmt))


def promote(
    db: Session,
    entity_ids: list[int],
    *,
    parent_id: int | None = None,
    category_id: int | None = None,
    set_category: bool = False,
    tags: list[str] | None = None,
    clear_draft: bool = True,
) -> tuple[list[Entity], list[dict]]:
    """File DRAFTS: optional move + category set + tag REPLACE, then draft=False.

    Promote's contract is drafts only — a non-draft entity (the Inbox included)
    is a per-entity error, never silently re-filed. Batch-level references
    (parent, category) are validated up front — a bad id 404s the whole call;
    per-entity failures are isolated via SAVEPOINTs and collected as
    {entity_id, message} without aborting the rest. Duplicate ids are collapsed
    (first occurrence wins) so one entity can never run twice in a batch.
    """
    if parent_id is not None:
        tree.get_entity(db, parent_id)  # NotFoundError -> 404 for the whole batch
    if set_category and category_id is not None and db.get(Category, category_id) is None:
        raise NotFoundError(f"Category {category_id} not found")

    promoted: list[Entity] = []
    errors: list[dict] = []
    for entity_id in dict.fromkeys(entity_ids):  # dedupe, order preserved
        savepoint = db.begin_nested()
        try:
            entity = tree.get_entity(db, entity_id)
            if tree.is_protected(db, entity):
                raise RuleViolation("The Inbox cannot be promoted")
            if not entity.draft:
                raise RuleViolation(f"Entity {entity_id} is not a draft")
            # Same-parent moves are skipped (re-filing into the Inbox is
            # allowed and still clears the draft flag below).
            if parent_id is not None and parent_id != entity.parent_id:
                tree.move_entity(db, entity_id, parent_id, commit=False)
            if set_category:
                tree.update_entity(db, entity_id, {"category_id": category_id}, commit=False)
            if tags is not None:
                metadata_svc.set_entity_tags(db, entity_id, tags, commit=False)
            if clear_draft:
                entity.draft = False
            db.flush()  # surface UNIQUE collisions etc. inside the savepoint
            savepoint.commit()
        except (TreeError, IntegrityError) as exc:
            savepoint.rollback()
            message = (
                "Conflicts with another entity (unique constraint)"
                if isinstance(exc, IntegrityError)
                else str(exc)
            )
            errors.append({"entity_id": entity_id, "message": message})
        else:
            promoted.append(entity)
    db.commit()
    return promoted, errors
