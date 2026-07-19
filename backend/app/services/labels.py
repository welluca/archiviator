"""Labels service: asset-tag allocation, sticker lifecycle, print batches.

Asset tags are PREFIX-NNNN (default prefix 'A', zero-padded to 4, growing
naturally past 9999). Tags are normalized (trim + uppercase) at EVERY entry
point — resolver, claim, assign — so scans and hand-typed input are
case-insensitive. Allocation is a single atomic UPDATE .. RETURNING on
tag_sequence (never read-then-write); it does NOT commit, so a failing caller
rolls the sequence back with the rest of its transaction.

Domain errors reuse tree.NotFoundError / tree.RuleViolation (404 / 409).
Every entity.asset_tag write goes through the ORM so the entity AU trigger
(AFTER UPDATE OF ... asset_tag) keeps search_fts in sync.
"""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entity import Entity
from app.models.labels import LabelBatch, LabelTemplate, PrintedLabel, TagSequence
from app.models.meta import Meta
from app.services import tree
from app.services.labelpdf import LabelSpec, render_batch_pdf
from app.services.tree import NotFoundError, RuleViolation
from app.utils.dt import utcnow

DEFAULT_PREFIX = "A"


def normalize_tag(tag: str) -> str:
    """Canonical tag form used everywhere: trimmed + uppercased."""
    return tag.strip().upper()


def format_tag(prefix: str, value: int) -> str:
    return f"{prefix}-{value:04d}"


def get_base_url(db: Session) -> str:
    """QR payload host from the meta row 'base_url' (never hardcoded)."""
    value = db.scalar(select(Meta.value).where(Meta.key == "base_url"))
    return (value or get_settings().base_url).rstrip("/")


def qr_payload(base_url: str, tag: str) -> str:
    return f"{base_url}/a/{tag}"


# --- allocation ---------------------------------------------------------------


def allocate_tags(db: Session, prefix: str = DEFAULT_PREFIX, n: int = 1) -> list[str]:
    """Reserve n sequence numbers atomically (single UPDATE .. RETURNING) and
    return the formatted tags. Does not commit — joins the caller's transaction."""
    stmt = (
        update(TagSequence)
        .where(TagSequence.prefix == prefix)
        .values(next_value=TagSequence.next_value + n)
        .returning(TagSequence.next_value)
    )
    new_next = db.execute(stmt).scalar_one_or_none()
    if new_next is None:  # unseeded prefix — create it and retry the same statement
        db.add(TagSequence(prefix=prefix, next_value=1))
        db.flush()
        new_next = db.execute(stmt).scalar_one()
    return [format_tag(prefix, value) for value in range(new_next - n, new_next)]


def _tag_taken(db: Session, tag: str) -> bool:
    """A sequence tag can be squatted by a free-form assign or an old sticker."""
    if db.scalar(select(Entity.id).where(Entity.asset_tag == tag)) is not None:
        return True
    return db.scalar(select(PrintedLabel.id).where(PrintedLabel.asset_tag == tag)) is not None


def allocate_free_tags(db: Session, n: int, prefix: str = DEFAULT_PREFIX) -> list[str]:
    """Allocate n tags, skipping any already taken (e.g. hand-assigned 'A-0007').
    Terminates because the sequence grows monotonically past any finite squat set."""
    free: list[str] = []
    while len(free) < n:
        free.extend(t for t in allocate_tags(db, prefix, n - len(free)) if not _tag_taken(db, t))
    return free


# --- lookups ------------------------------------------------------------------


def _get_label(db: Session, tag: str) -> PrintedLabel:
    label = db.scalars(select(PrintedLabel).where(PrintedLabel.asset_tag == tag)).first()
    if label is None:
        raise NotFoundError(f"Label {tag} not found")
    return label


def _get_template(db: Session, template_id: int) -> LabelTemplate:
    template = db.get(LabelTemplate, template_id)
    if template is None:
        raise NotFoundError(f"Label template {template_id} not found")
    return template


def get_batch(db: Session, batch_id: int) -> LabelBatch:
    batch = db.get(LabelBatch, batch_id)
    if batch is None:
        raise NotFoundError(f"Label batch {batch_id} not found")
    return batch


def list_templates(db: Session) -> list[LabelTemplate]:
    return list(db.scalars(select(LabelTemplate).order_by(LabelTemplate.id)))


def resolve(db: Session, tag: str) -> tuple[str, Entity | PrintedLabel]:
    """('entity', Entity) for a tag bound to an entity, ('unclaimed', PrintedLabel)
    for a printed-but-unbound sticker; NotFoundError otherwise (incl. void)."""
    tag = normalize_tag(tag)
    entity = db.scalars(select(Entity).where(Entity.asset_tag == tag)).first()
    if entity is not None:
        return "entity", entity
    label = db.scalars(
        select(PrintedLabel).where(
            PrintedLabel.asset_tag == tag, PrintedLabel.status == "unclaimed"
        )
    ).first()
    if label is not None:
        return "unclaimed", label
    raise NotFoundError(f"Tag {tag} not found")


# --- claim / void -------------------------------------------------------------


def _commit_or_conflict(db: Session) -> None:
    """Commit, translating a UNIQUE collision (concurrent tag writers) to a 409
    instead of an unhandled 500."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RuleViolation("Asset tag already in use") from exc


def _bind(db: Session, label: PrintedLabel, entity: Entity) -> None:
    """Claim the sticker and stamp the entity's tag via guarded UPDATEs whose
    WHERE clauses re-check state at write time (no commit here). A concurrent
    claim then affects 0 rows and raises — the transaction rolls back whole —
    instead of leaving a stranded 'claimed' sticker.
    """
    expected = entity.asset_tag  # value read in THIS transaction (None unless replacing)
    claimed = db.execute(
        update(PrintedLabel)
        .where(PrintedLabel.id == label.id, PrintedLabel.status == "unclaimed")
        .values(status="claimed", entity_id=entity.id, claimed_at=utcnow())
    ).rowcount
    if claimed != 1:
        raise RuleViolation(f"Label {label.asset_tag} is no longer unclaimed")
    stmt = update(Entity).where(Entity.id == entity.id)
    stmt = stmt.where(
        Entity.asset_tag.is_(None) if expected is None else Entity.asset_tag == expected
    )
    # DB-level UPDATE still fires the entity AU trigger -> fts stays in sync.
    tagged = db.execute(
        stmt.values(asset_tag=label.asset_tag, updated_at=utcnow())
    ).rowcount
    if tagged != 1:
        raise RuleViolation(f"Entity {entity.id}'s asset tag changed concurrently")
    db.expire_all()


def _guard_claimable(db: Session, label: PrintedLabel, entity: Entity) -> None:
    if tree.is_protected(db, entity):
        raise RuleViolation("The Inbox cannot be tagged")
    if entity.asset_tag is not None:
        raise RuleViolation(
            f"Entity {entity.id} already has asset tag {entity.asset_tag}"
        )


def claim(
    db: Session,
    tag: str,
    *,
    entity_id: int | None = None,
    create: dict | None = None,
) -> Entity:
    """Bind an unclaimed printed label to an existing entity, or to a freshly
    created one (create runs the normal containment rules).

    Existing-entity path is ONE transaction. The create path reuses
    tree.create_entity (which commits), then claims in a second step with a
    compensating delete on failure — same pattern as metadata.duplicate_entity —
    so a failed claim leaves no orphan entity and the label stays unclaimed.
    """
    tag = normalize_tag(tag)
    label = _get_label(db, tag)
    if label.status != "unclaimed":
        raise RuleViolation(f"Label {tag} is {label.status}, not unclaimed")

    if entity_id is not None:
        entity = tree.get_entity(db, entity_id)
        _guard_claimable(db, label, entity)
        _bind(db, label, entity)
        _commit_or_conflict(db)
        return entity

    assert create is not None
    entity = tree.create_entity(db, **create)  # commits (or raises before any write)
    try:
        label = _get_label(db, tag)  # re-fetch in the new transaction
        if label.status != "unclaimed":
            raise RuleViolation(f"Label {tag} is {label.status}, not unclaimed")
        _bind(db, label, entity)
        _commit_or_conflict(db)
    except Exception:
        db.rollback()
        try:
            leftover = db.get(Entity, entity.id)
            if leftover is not None:
                db.delete(leftover)
                db.commit()
        except Exception:
            db.rollback()  # cleanup failed — the original error still wins
        raise
    return entity


def void(db: Session, tag: str) -> PrintedLabel:
    """Void a ruined/lost sticker. Allowed for unclaimed labels and for orphaned
    'claimed' labels no entity actually carries (the repair path for historical
    inconsistencies); a label bound to a live entity is a 409 — remove the tag
    from the entity instead."""
    tag = normalize_tag(tag)
    label = _get_label(db, tag)
    if label.status == "void":
        raise RuleViolation(f"Label {tag} is already void")
    in_use = db.scalar(select(func.count(Entity.id)).where(Entity.asset_tag == tag))
    if in_use:
        raise RuleViolation(
            f"Label {tag} is bound to an entity; remove the tag from the entity instead"
        )
    label.status = "void"
    label.entity_id = None
    label.claimed_at = None
    db.commit()
    return label


# --- entity asset-tag assignment ----------------------------------------------


def _release_label_for(db: Session, tag: str | None) -> None:
    """Revert the claimed sticker carrying `tag` (if any) to unclaimed — the
    physical label still exists and can be re-bound later. No commit here."""
    if tag is None:
        return
    label = db.scalars(
        select(PrintedLabel).where(
            PrintedLabel.asset_tag == tag, PrintedLabel.status == "claimed"
        )
    ).first()
    if label is not None:
        label.status = "unclaimed"
        label.entity_id = None
        label.claimed_at = None


def assign_asset_tag(
    db: Session,
    entity_id: int,
    *,
    tag: str | None = None,
    auto: bool = False,
    commit: bool = True,
) -> Entity:
    """All contract branches of POST /entities/{id}/asset-tag:

    auto=True     allocate the next free sequence tag (no printed_label row —
                  a tag can exist without a printed sticker).
    tag='...'     custom tag: an UNCLAIMED printed label with that tag is
                  claimed; a claimed/void label or another entity's tag is a
                  409; otherwise free-form assign.
    tag=None      clear — a printed label claimed with the old tag reverts to
                  unclaimed.
    Replacing an existing tag releases its claimed sticker in the same
    transaction (one commit). commit=False joins the caller's transaction
    (CSV import) — UNIQUE collisions then surface at the caller's flush/commit."""
    entity = tree.get_entity(db, entity_id)

    if not auto and tag is None:  # clear
        if entity.asset_tag is not None:
            _release_label_for(db, entity.asset_tag)
            entity.asset_tag = None
            if commit:
                db.commit()
        return entity

    if tree.is_protected(db, entity):
        raise RuleViolation("The Inbox cannot be tagged")

    if auto:
        new_tag = allocate_free_tags(db, 1)[0]
        _release_label_for(db, entity.asset_tag)
        entity.asset_tag = new_tag
        if commit:
            _commit_or_conflict(db)
        return entity

    new_tag = normalize_tag(tag)
    if not new_tag:
        raise RuleViolation("Asset tag must not be blank")
    if entity.asset_tag == new_tag:
        return entity  # no-op

    other = db.scalars(
        select(Entity).where(Entity.asset_tag == new_tag, Entity.id != entity.id)
    ).first()
    if other is not None:
        raise RuleViolation(f"Asset tag {new_tag} is already assigned to entity {other.id}")

    label = db.scalars(select(PrintedLabel).where(PrintedLabel.asset_tag == new_tag)).first()
    if label is not None and label.status != "unclaimed":
        raise RuleViolation(f"Asset tag {new_tag} belongs to a {label.status} label")

    _release_label_for(db, entity.asset_tag)
    if label is not None:  # unclaimed printed sticker -> full claim
        _bind(db, label, entity)
    else:  # free-form assign
        entity.asset_tag = new_tag
    if commit:
        _commit_or_conflict(db)
    return entity


def release_on_entity_delete(db: Session, entity: Entity) -> None:
    """tree.delete_entity hook: a claimed sticker whose entity goes away reverts
    to 'unclaimed' (it is still physically out there and can be re-bound).
    Joins the delete transaction — no commit here."""
    _release_label_for(db, entity.asset_tag)


# --- batches ------------------------------------------------------------------


def _parent_crumb(entity: Entity) -> str | None:
    """Breadcrumb of the CONTAINER chain (entity's own name stripped)."""
    crumb = entity.breadcrumb[: len(entity.breadcrumb) - len(entity.name)].rstrip()
    crumb = crumb[:-1].rstrip() if crumb.endswith("›") else crumb
    return crumb or None


def create_batch(
    db: Session,
    *,
    template_id: int,
    count: int | None = None,
    entity_ids: list[int] | None = None,
    skip_first: int = 0,
    note: str | None = None,
) -> tuple[LabelBatch, list[str]]:
    """Render a sticker sheet PDF; two modes, one transaction (a failed render
    rolls back rows AND sequence numbers). Returns (batch, rendered tags).

    count       allocate that many NEW tags as unclaimed printed_label rows
                (blank stickers to claim later).
    entity_ids  print labels for EXISTING entities, allocating tags for those
                without one; rows are created as 'claimed'. A tag already
                tracked by an earlier batch keeps its original printed_label
                row (asset_tag is UNIQUE) — the PDF still includes the label.
    skip_first  leaves N leading positions empty (partially used sheet).
    """
    template = _get_template(db, template_id)
    if (count is None) == (entity_ids is None):
        raise RuleViolation("Provide exactly one of count or entity_ids")
    capacity = template.cols * template.rows
    if not 0 <= skip_first < capacity:
        raise RuleViolation(
            f"skip_first must be between 0 and {capacity - 1} "
            f"(positions already used on the first sheet)"
        )

    base_url = get_base_url(db)
    batch = LabelBatch(template_id=template.id, note=note)
    db.add(batch)
    db.flush()  # assigns batch.id, needed for the pdf filename

    specs: list[LabelSpec] = []
    if count is not None:
        if count < 1:
            raise RuleViolation("count must be >= 1")
        for tag in allocate_free_tags(db, count):
            db.add(PrintedLabel(batch_id=batch.id, asset_tag=tag))
            specs.append(LabelSpec(tag=tag, qr_payload=qr_payload(base_url, tag)))
    else:
        if not entity_ids:
            raise RuleViolation("entity_ids must not be empty")
        entity_ids = list(dict.fromkeys(entity_ids))  # dedupe, keep print order
        entities = [tree.get_entity(db, entity_id) for entity_id in entity_ids]
        untagged = [e for e in entities if e.asset_tag is None]
        for entity in entities:
            if tree.is_protected(db, entity):
                raise RuleViolation("The Inbox cannot be labeled")
        fresh = iter(allocate_free_tags(db, len(untagged)) if untagged else [])
        for entity in untagged:
            entity.asset_tag = next(fresh)  # ORM update -> AU trigger syncs fts
        tracked = set(
            db.scalars(
                select(PrintedLabel.asset_tag).where(
                    PrintedLabel.asset_tag.in_([e.asset_tag for e in entities])
                )
            )
        )
        for entity in entities:
            if entity.asset_tag not in tracked:
                db.add(
                    PrintedLabel(
                        batch_id=batch.id,
                        asset_tag=entity.asset_tag,
                        status="claimed",
                        entity_id=entity.id,
                        claimed_at=utcnow(),
                    )
                )
            specs.append(
                LabelSpec(
                    tag=entity.asset_tag,
                    qr_payload=qr_payload(base_url, entity.asset_tag),
                    name=entity.name,
                    breadcrumb=_parent_crumb(entity),
                )
            )

    pdf_rel = f"labels/batch-{batch.id:04d}.pdf"
    pdf_abs = get_settings().data_dir / pdf_rel
    pdf_abs.parent.mkdir(parents=True, exist_ok=True)
    try:
        render_batch_pdf(template, specs, str(pdf_abs), skip_first=skip_first)
    except Exception:
        db.rollback()  # rows + sequence numbers all revert together
        raise
    batch.pdf_path = pdf_rel
    _commit_or_conflict(db)
    # Return what was RENDERED (mode 2 can reprint tags tracked by earlier
    # batches — those rows belong to the old batch but are on this PDF).
    return batch, [spec.tag for spec in specs]


def labels_by_tags(db: Session, tags: list[str]) -> list[tuple[PrintedLabel, str | None]]:
    """(label, entity_name) rows for the given tags, in the given (print) order."""
    if not tags:
        return []
    stmt = (
        select(PrintedLabel, Entity.name)
        .outerjoin(Entity, Entity.id == PrintedLabel.entity_id)
        .where(PrintedLabel.asset_tag.in_(tags))
    )
    by_tag = {label.asset_tag: (label, name) for label, name in db.execute(stmt)}
    return [by_tag[t] for t in tags if t in by_tag]


def batch_labels(db: Session, batch_id: int) -> list[tuple[PrintedLabel, str | None]]:
    """(label, entity_name) rows of a batch, print order."""
    stmt = (
        select(PrintedLabel, Entity.name)
        .outerjoin(Entity, Entity.id == PrintedLabel.entity_id)
        .where(PrintedLabel.batch_id == batch_id)
        .order_by(PrintedLabel.id)
    )
    return [(label, name) for label, name in db.execute(stmt)]


def batch_status_counts(db: Session, batch_ids: list[int] | None = None) -> dict[int, dict[str, int]]:
    """{batch_id: {'unclaimed': n, 'claimed': n, 'void': n}} — ONE grouped query."""
    stmt = select(
        PrintedLabel.batch_id, PrintedLabel.status, func.count(PrintedLabel.id)
    ).group_by(PrintedLabel.batch_id, PrintedLabel.status)
    if batch_ids is not None:
        if not batch_ids:
            return {}
        stmt = stmt.where(PrintedLabel.batch_id.in_(batch_ids))
    out: dict[int, dict[str, int]] = {}
    for batch_id, label_status, n in db.execute(stmt):
        out.setdefault(batch_id, {"unclaimed": 0, "claimed": 0, "void": 0})[label_status] = n
    return out


def list_batches(db: Session) -> list[LabelBatch]:
    return list(db.scalars(select(LabelBatch).order_by(LabelBatch.id.desc())))
