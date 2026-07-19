"""Search service: FTS5 MATCH building, the filtered/ranked entity query, and
the index rebuild safety net.

The MATCH string is built ONLY from sanitized tokens, each double-quoted with a
trailing * for prefix search — raw user input (quotes, NEAR, AND/OR, columns)
can never reach the FTS5 query parser. Filters mirror the tree-endpoint
semantics: `under` uses the index-usable subtree range predicate and archived
entities hide their WHOLE subtree exactly like tree.list_tree.
"""

import re

from sqlalchemy import column, exists, func, literal_column, select, table, text
from sqlalchemy.orm import Session, aliased

from app.models.attachment import Attachment
from app.models.entity import Entity
from app.models.metadata import EntityTag, Tag
from app.services import tree

# bm25 weights in fts column order: name, description, breadcrumb, tags, fields, asset_tag.
# asset_tag is meant to outrank a name hit, and a name hit always co-hits the
# breadcrumb column (10 + 3 = 13 weighted occurrences) — hence 16, not just >10.
_BM25 = "bm25(search_fts, 10.0, 2.0, 3.0, 6.0, 4.0, 16.0)"

_search_fts = table("search_fts", column("rowid"))

_TOKEN_JUNK = re.compile(r"[^\w\-]")


def build_match(q: str | None) -> str | None:
    """Sanitized MATCH expression: per token keep only [\\w-] chars, drop tokens
    without an ASCII alphanumeric (underscores/hyphens are FTS5 separators, so
    e.g. "___" would be an EMPTY phrase matching nothing instead of a no-op),
    quote each as "tok"* (prefix), join with spaces (implicit AND). None when
    nothing searchable survives (pure filter browse)."""
    if not q:
        return None
    phrases = []
    for raw in q.split():
        token = _TOKEN_JUNK.sub("", raw)
        if not re.search(r"[0-9A-Za-z]", token):
            continue
        phrases.append(f'"{token}"*')
    return " ".join(phrases) or None


def search_entities(
    db: Session,
    *,
    q: str | None = None,
    kind: str | None = None,
    tag_names: list[str] | None = None,
    category_id: int | None = None,
    under: int | None = None,
    has_photo: bool | None = None,
    include_archived: bool = False,
    limit: int = 50,
) -> list[Entity]:
    match = build_match(q)
    stmt = select(Entity)
    if match is not None:
        stmt = (
            stmt.join(_search_fts, _search_fts.c.rowid == Entity.id)
            .where(text("search_fts MATCH :match").bindparams(match=match))
            .order_by(literal_column(_BM25), func.lower(Entity.name))
        )
    else:
        stmt = stmt.order_by(func.lower(Entity.name))

    if kind is not None:
        stmt = stmt.where(Entity.kind == kind)
    if category_id is not None:
        stmt = stmt.where(Entity.category_id == category_id)
    if under is not None:
        anchor = tree.get_entity(db, under)  # unknown id -> 404
        stmt = stmt.where(tree.subtree_range_filter(anchor.path))
    for name in tag_names or ():
        # AND of tags: one EXISTS per name (tag.name is COLLATE NOCASE).
        stmt = stmt.where(
            select(EntityTag.tag_id)
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(EntityTag.entity_id == Entity.id, Tag.name == name)
            .exists()
        )
    if has_photo is not None:
        photo = (
            select(Attachment.id)
            .where(Attachment.entity_id == Entity.id, Attachment.type == "photo")
            .exists()
        )
        stmt = stmt.where(photo if has_photo else ~photo)
    if not include_archived:
        # Hide the WHOLE archived subtree (same semantics as tree.list_tree):
        # an entity is hidden when any prefix of its path is an archived row's
        # path — including the entity itself.
        ancestor = aliased(Entity)
        hidden = exists(
            select(ancestor.id).where(
                ancestor.archived_at.is_not(None),
                func.substr(Entity.path, 1, func.length(ancestor.path)) == ancestor.path,
            )
        )
        stmt = stmt.where(~hidden)

    return list(db.scalars(stmt.limit(limit)))


# Mirrors the trigger SQL in alembic/versions/0004_metadata.py — keep in sync.
_REFILL_SQL = """
INSERT INTO search_fts(rowid, name, description, breadcrumb, tags, fields, asset_tag)
SELECT e.id, e.name, COALESCE(e.description, ''), e.breadcrumb,
    COALESCE((SELECT group_concat(t.name, ' ') FROM entity_tag et
              JOIN tag t ON t.id = et.tag_id WHERE et.entity_id = e.id), ''),
    COALESCE((SELECT group_concat(fd.name || ' ' || fv.value_text, ' ') FROM field_value fv
              JOIN field_def fd ON fd.id = fv.field_def_id WHERE fv.entity_id = e.id), ''),
    COALESCE(e.asset_tag, '')
FROM entity e
"""


def rebuild_search(db: Session) -> int:
    """Drop and refill search_fts from the live rows (admin safety net); returns
    the number of indexed entities."""
    db.execute(text("DELETE FROM search_fts"))
    db.execute(text(_REFILL_SQL))
    db.commit()
    return db.scalar(text("SELECT count(*) FROM search_fts"))
