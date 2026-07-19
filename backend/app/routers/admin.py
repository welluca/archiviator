"""Admin router: maintenance operations — FTS rebuild (M4), backups, CSV
import/export and the full-archive ZIP export (M6).

CSV responses are built fully in the endpoint (not streamed lazily): FastAPI
closes yield-dependencies before the body streams, so a lazy generator would
read from a closed session. The ZIP streams from a spooled temp file instead —
it never touches the request's DB session.
"""

import tempfile
import uuid
import zipfile
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.config import get_settings
from app.dependencies import DbSession, get_current_user
from app.services import backup, io_csv, search

router = APIRouter(dependencies=[Depends(get_current_user)])

# Everything in data_dir the ZIP archive carries; derived/ is EXCLUDED because
# thumbnails/display sizes are regenerable from the originals.
ZIP_DIRS = ("attachments", "labels", "floorplans")


class RebuildSearchResult(BaseModel):
    indexed: int


class BackupResult(BaseModel):
    file: str
    bytes: int


class BackupInfo(BaseModel):
    file: str
    bytes: int
    created_at: datetime


class ImportRowError(BaseModel):
    row: int
    message: str


class ImportResult(BaseModel):
    created: int
    updated: int
    errors: list[ImportRowError]
    dry_run: bool


@router.post("/rebuild-search", response_model=RebuildSearchResult)
async def rebuild_search(db: DbSession):
    """Drop and refill search_fts from the live rows — safety net for a
    corrupted or out-of-sync index."""
    return RebuildSearchResult(indexed=search.rebuild_search(db))


# --- backups ------------------------------------------------------------------


@router.post("/backup-now", response_model=BackupResult)
def backup_now():
    """On-demand snapshot — exactly the nightly job body. Plain def: VACUUM INTO
    is sync/heavy, so FastAPI must run it in the threadpool, not on the loop."""
    return BackupResult(**backup.run_backup(get_settings().data_dir))


@router.get("/backups", response_model=list[BackupInfo])
async def list_backups():
    return backup.list_backups(get_settings().data_dir)


# --- CSV ----------------------------------------------------------------------


@router.get("/export.csv")
def export_csv(db: DbSession, dialect: Literal["homebox"] | None = None):
    # Plain def (threadpool): builds the whole CSV synchronously.
    body = "".join(io_csv.export_rows(db, dialect=dialect))
    filename = "archiviator-homebox.csv" if dialect else "archiviator-export.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import-csv", response_model=ImportResult)
def import_csv(db: DbSession, file: UploadFile = File(...), dry_run: bool = False):
    # Plain def (threadpool): the import is one big sync transaction.
    raw = file.file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File is not valid UTF-8 text",
        )
    try:
        return io_csv.import_csv(db, text, dry_run=dry_run)
    except io_csv.MalformedCsvError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )


# --- full-archive ZIP ---------------------------------------------------------


def _stream_and_close(fh, chunk_size: int = 64 * 1024):
    try:
        while chunk := fh.read(chunk_size):
            yield chunk
    finally:
        fh.close()


@router.get("/export.zip")
def export_zip():
    """db-snapshot.db (fresh VACUUM INTO) + attachments/labels/floorplans trees;
    derived/ excluded (regenerable). Spooled to temp, then streamed. Plain def:
    the snapshot + ZIP compression can take minutes and must not block the loop."""
    settings = get_settings()
    data_dir = settings.data_dir
    spool = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    try:
        with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as archive:
            snapshot = data_dir / f"db-snapshot-{uuid.uuid4().hex}.tmp"
            try:
                backup.snapshot_to(settings.db_path, snapshot)
                archive.write(snapshot, "db-snapshot.db")
            finally:
                snapshot.unlink(missing_ok=True)
            for sub in ZIP_DIRS:
                base = data_dir / sub
                if not base.exists():
                    continue
                for path in sorted(base.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(data_dir).as_posix())
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return StreamingResponse(
        _stream_and_close(spool),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="archiviator-export.zip"'},
    )
