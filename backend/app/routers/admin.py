"""Admin router: maintenance operations (M4: FTS search index rebuild)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import DbSession, get_current_user
from app.services import search

router = APIRouter(dependencies=[Depends(get_current_user)])


class RebuildSearchResult(BaseModel):
    indexed: int


@router.post("/rebuild-search", response_model=RebuildSearchResult)
async def rebuild_search(db: DbSession):
    """Drop and refill search_fts from the live rows — safety net for a
    corrupted or out-of-sync index."""
    return RebuildSearchResult(indexed=search.rebuild_search(db))
