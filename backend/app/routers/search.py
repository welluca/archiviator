"""Search router: filtered/ranked entity search over the FTS5 index (M4).

Thin surface over app.services.search; results reuse the EntityOut batch
helpers so tags/thumbs/counts stay N+1-free.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.dependencies import DbSession, get_current_user
from app.routers.entities import (
    EntityOut,
    Kind,
    _out,
    _tags_map,
    _thumb_map,
    domain_errors,
)
from app.services import search as svc
from app.services import tree

router = APIRouter(dependencies=[Depends(get_current_user)])


class SearchResults(BaseModel):
    results: list[EntityOut]


@router.get("/search", response_model=SearchResults)
async def search_entities(
    db: DbSession,
    q: str | None = None,
    kind: Kind | None = None,
    tags: str | None = None,
    category_id: int | None = None,
    under: int | None = None,
    has_photo: bool | None = None,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
):
    tag_names = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    with domain_errors():
        entities = svc.search_entities(
            db,
            q=q,
            kind=kind,
            tag_names=tag_names,
            category_id=category_id,
            under=under,
            has_photo=has_photo,
            include_archived=include_archived,
            limit=limit,
        )
    counts = tree.child_counts(db, [e.id for e in entities])
    inbox_id = tree.get_inbox_id(db)
    thumbs = _thumb_map(db, entities)
    tag_map = _tags_map(db, entities)
    return SearchResults(
        results=[_out(e, counts, inbox_id, thumbs, tag_map) for e in entities]
    )
