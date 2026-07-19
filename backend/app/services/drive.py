"""Google Drive service (M9): connection state, scans-folder poller, scan inbox,
drive_link attachments, thumbnail cache, reconciliation and backup push.

ALL Drive access goes through the thin DriveClient protocol below, obtained via
the module-level get_drive_client(db) factory — tests monkeypatch that factory
with an in-memory fake, so nothing in here can be reached with a real network
client during tests.

Storage:
- token: {data_dir}/gdrive/token.json (NEVER shipped in export.zip; contents
  never logged);
- client secret: settings.gdrive_credentials_file (env) OR the meta key
  'gdrive_credentials_file' — a path to Luca's existing client_secret_*.json,
  only ever read in place, never copied;
- thumbnails: {data_dir}/drive-cache/{file_id}/{md5}.jpg, served via /media
  (drive-cache/ is on the /media allowlist — subdirectories included; also
  excluded from export.zip). Per-id subdirectories keep hyphenated ids from
  colliding with each other's glob (the old flat '{id}-{md5}.jpg' scheme let
  id 'a' match the files of id 'a-b').

Connect flow: the InstalledAppFlow BLOCKS and opens a browser ON THE SERVER PC
(fine — server == Luca's PC), so POST /drive/connect spawns it on a worker
thread and returns 202; /drive/status surfaces progress via the token file +
the module-level _connect_pending flag.

Scheduling: the poll job interval is read from drive_account.poll_interval_min
when the scheduler is built at startup; interval changes take effect on service
restart OR immediately when the config PUT reschedules the job through
app.state.scheduler (reschedule_poll below).
"""

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.attachment import Attachment
from app.models.drive import DriveAccount, ScanInbox
from app.models.entity import Entity
from app.models.meta import Meta
from app.services import backup
from app.services.tree import NotFoundError, RuleViolation
from app.utils.dt import utcnow

logger = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
META_CREDENTIALS_KEY = "gdrive_credentials_file"
BACKUP_FOLDER_NAME = "Archiviator Backups"
DRIVE_BACKUP_KEEP = 7
POLL_OVERLAP = timedelta(minutes=5)


# --- DriveClient protocol + factory -------------------------------------------


class FolderGoneError(Exception):
    """Raised by DriveClient.upload_file when the target parent folder no
    longer exists on Drive (HttpError 404 on the real client). Part of the
    protocol contract: callers holding a cached folder id may drop the cache,
    re-ensure the folder once and retry the upload once."""


class DriveClient(Protocol):
    """The thin surface app code programs against; implemented for real by
    app.gdrive.client.GDriveClient and by FakeDriveClient in tests."""

    def list_children(self, folder_id: str) -> list[dict]: ...

    def file_metadata(self, file_id: str) -> dict | None: ...

    def download_thumbnail(self, url: str) -> bytes | None: ...

    def upload_file(
        self, local_path: str, parent_folder_id: str, filename: str | None = None
    ) -> dict:
        """Raises FolderGoneError when parent_folder_id no longer exists."""
        ...

    def ensure_folder(self, name: str, parent: str | None = None) -> str: ...

    def delete_file(self, file_id: str) -> bool: ...

    def user_email(self) -> str | None: ...


def get_drive_client(db: Session) -> DriveClient:
    """Factory for the REAL client (tests monkeypatch this module attribute).
    Raises RuleViolation (409) when not connected. Imports are lazy so the
    google libraries never load unless a real client is actually built."""
    from app.gdrive.auth import load_credentials
    from app.gdrive.client import GDriveClient

    creds = load_credentials(token_path())
    if creds is None:
        raise RuleViolation("Google Drive is not connected")
    return GDriveClient(creds)


def run_installed_flow(credentials_file: str, token_file: Path) -> None:
    """Thin patchable wrapper over the blocking browser OAuth flow."""
    from app.gdrive.auth import run_installed_flow as _real_flow

    _real_flow(credentials_file, token_file)


# --- paths / state helpers ----------------------------------------------------


def token_path() -> Path:
    return get_settings().data_dir / "gdrive" / "token.json"


def drive_cache_dir() -> Path:
    return get_settings().data_dir / "drive-cache"


def is_connected() -> bool:
    """'Connected' == a plausible token file exists (validity is only provable
    on the wire; a dead token surfaces as a 409 on the next Drive call)."""
    try:
        data = json.loads(token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(data.get("refresh_token") or data.get("token"))


def get_account(db: Session) -> DriveAccount:
    account = db.get(DriveAccount, 1)
    if account is None:  # unreachable after migration 0008, but never guess
        raise NotFoundError("drive_account row is missing")
    return account


def credentials_path(db: Session) -> str | None:
    """Client-secret path: env setting wins, else the meta row."""
    configured = get_settings().gdrive_credentials_file
    if configured:
        return str(configured)
    return db.scalar(select(Meta.value).where(Meta.key == META_CREDENTIALS_KEY))


def _parse_rfc3339(value: str) -> datetime:
    """Drive RFC3339 (with Z / fraction) -> naive-UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _format_rfc3339(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def _safe_name(value: str) -> str:
    """Sanitize Drive ids/md5s for cache filenames (both are normally URL-safe
    already; this is belt and braces against path tricks)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def _validate_file_id(file_id: str) -> None:
    """Reject path-like 'file ids' with a 409 BEFORE any filesystem use. Real
    Drive ids are URL-safe; anything carrying separators or dot segments could
    otherwise be aimed at paths outside drive-cache/."""
    if not file_id or "/" in file_id or "\\" in file_id or ".." in file_id or file_id == ".":
        raise RuleViolation("Invalid Drive file id")


def _thumb_dir(file_id: str) -> Path:
    """Per-file thumbnail cache directory: drive-cache/{fileId}/."""
    return drive_cache_dir() / _safe_name(file_id)


# --- status / config ----------------------------------------------------------


def get_status(db: Session) -> dict:
    account = get_account(db)
    counts = {"new": 0, "attached": 0, "ignored": 0}
    for status_value, n in db.execute(
        select(ScanInbox.status, func.count()).group_by(ScanInbox.status)
    ):
        counts[status_value] = n
    scans_folder = None
    if account.scans_folder_id:
        scans_folder = {"id": account.scans_folder_id, "name": account.scans_folder_name}
    return {
        "configured": bool(credentials_path(db)),
        "connected": is_connected(),
        "connect_pending": _connect_pending,
        "email": account.email,
        "scans_folder": scans_folder,
        "poll_interval_min": account.poll_interval_min,
        "backup_upload_enabled": account.backup_upload_enabled,
        "last_poll_at": account.last_poll_at,
        "last_backup_upload_at": account.last_backup_upload_at,
        "inbox_counts": counts,
    }


def _validate_credentials_file(path: str) -> None:
    """The secret must exist and be a desktop-app OAuth client JSON ('installed'
    top-level key) -> RuleViolation (409) otherwise. Read in place, never copied."""
    p = Path(path)
    if not p.is_file():
        raise RuleViolation(f"Client secret file not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuleViolation("Client secret file is not valid JSON")
    if not isinstance(data, dict) or "installed" not in data:
        raise RuleViolation(
            "Client secret JSON has no 'installed' key — export a Desktop-app OAuth client"
        )


def update_config(db: Session, changes: dict) -> None:
    """Apply a PUT /drive/config payload (exclude_unset dict). Numeric bounds
    are enforced by the router's pydantic model (422); file validation is a
    domain rule (409). credentials_path: null CLEARS the stored meta path
    (configured -> false — unless the GDRIVE_CREDENTIALS_FILE env setting is
    set, which always wins in credentials_path())."""
    if "credentials_path" in changes:
        path = changes["credentials_path"]
        row = db.get(Meta, META_CREDENTIALS_KEY)
        if path is None:
            if row is not None:
                db.delete(row)
        else:
            _validate_credentials_file(path)
            if row is None:
                db.add(Meta(key=META_CREDENTIALS_KEY, value=path))
            else:
                row.value = path
    account = get_account(db)
    if "scans_folder_id" in changes:
        if changes["scans_folder_id"] != account.scans_folder_id:
            # A different folder makes the old poll anchor meaningless: null it
            # so the next scan ingests the FULL listing with no cutoff.
            account.last_poll_at = None
        account.scans_folder_id = changes["scans_folder_id"]
    if "scans_folder_name" in changes:
        account.scans_folder_name = changes["scans_folder_name"]
    if changes.get("poll_interval_min") is not None:
        account.poll_interval_min = changes["poll_interval_min"]
    if changes.get("backup_upload_enabled") is not None:
        account.backup_upload_enabled = changes["backup_upload_enabled"]
    db.commit()


def reschedule_poll(scheduler, minutes: int) -> None:
    """Re-register the poll job with a new interval on a live scheduler.
    Tolerates scheduler=None (disabled in tests / config) — the new interval
    then simply applies on the next service restart."""
    if scheduler is None:
        return
    from apscheduler.triggers.interval import IntervalTrigger

    from app.services.scheduler import DRIVE_POLL_JOB_ID, drive_poll

    try:
        scheduler.remove_job(DRIVE_POLL_JOB_ID)
    except Exception:  # job not registered (or pending) — add below either way
        pass
    scheduler.add_job(
        drive_poll,
        IntervalTrigger(minutes=minutes),
        id=DRIVE_POLL_JOB_ID,
        name="Google Drive scans-folder poll",
        replace_existing=True,
    )


# --- connect / disconnect -----------------------------------------------------

_connect_pending = False
# RACE GUARD: each connect attempt is stamped with a generation; disconnect
# (and every new attempt) bumps it. A worker whose generation is stale must
# neither clear the pending flag of a NEWER attempt nor keep the token its
# consent flow wrote — otherwise "disconnect while the consent tab is open,
# then finish the consent" would silently rewrite token.json and reconnect an
# account the user explicitly disconnected.
_connect_generation = 0
_connect_lock = threading.Lock()
_connect_thread: threading.Thread | None = None


def start_connect(db: Session) -> None:
    """Kick off the interactive OAuth flow on a worker thread (it blocks and
    opens a browser ON THE SERVER PC). 409 when no client secret is configured;
    idempotent while a flow is already pending."""
    global _connect_pending, _connect_thread, _connect_generation
    secret = credentials_path(db)
    if not secret:
        raise RuleViolation("No Google client secret configured — set credentials_path first")
    with _connect_lock:
        if _connect_pending:
            return
        _connect_pending = True
        _connect_generation += 1
        generation = _connect_generation
    _connect_thread = threading.Thread(
        target=_connect_worker, args=(secret, generation), daemon=True, name="gdrive-connect"
    )
    _connect_thread.start()


def _connect_worker(secret: str, generation: int) -> None:
    global _connect_pending
    try:
        run_installed_flow(secret, token_path())
        # The flow itself persisted token.json — check the generation BEFORE
        # treating it as the connected state (see the race note above). A tiny
        # write-then-unlink window remains; harmless, the unlink always runs.
        with _connect_lock:
            stale = generation != _connect_generation
        if stale:
            token_path().unlink(missing_ok=True)
            return
        _store_account_email()
    except Exception:
        # Never log token contents; the exception text carries none.
        logger.exception("Google Drive connect flow failed")
    finally:
        with _connect_lock:
            # Only the CURRENT attempt may clear the flag — a stale thread
            # finishing late must not mark a newer attempt as done.
            if generation == _connect_generation:
                _connect_pending = False


def _store_account_email() -> None:
    """Post-connect: record the account email (own short-lived session — this
    runs on the worker thread, far from any request)."""
    from app.database import get_sessionmaker

    db = get_sessionmaker()()
    try:
        client = get_drive_client(db)
        email = client.user_email()
        account = get_account(db)
        account.email = email
        db.commit()
    except Exception:
        logger.exception("Could not read the connected account's email")
    finally:
        db.close()


def disconnect(db: Session) -> None:
    """Forget the token (delete token.json) and clear per-account state: email,
    last_poll_at and backup_folder_id — a different account reconnecting later
    must inherit neither the poll cutoff nor a folder id it cannot see. The
    generation bump invalidates any in-flight connect flow (see _connect_worker).

    scan_inbox rows are KEPT deliberately: after a reconnect with a DIFFERENT
    account they may be stale (files the new account cannot access). Acceptable
    for now; an explicit 'clear inbox' action is left for later."""
    global _connect_pending, _connect_generation
    with _connect_lock:
        _connect_generation += 1
        _connect_pending = False
    token_path().unlink(missing_ok=True)
    account = get_account(db)
    account.email = None
    account.last_poll_at = None
    account.backup_folder_id = None
    db.commit()


# --- browse -------------------------------------------------------------------


def browse(db: Session, folder_id: str) -> dict:
    """Folder-picker / attach-browser listing: children split into folders/files."""
    client = get_drive_client(db)
    folders, files = [], []
    for item in client.list_children(folder_id):
        if item.get("mimeType") == FOLDER_MIME:
            folders.append({"id": item["id"], "name": item["name"]})
        else:
            files.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "mime": item.get("mimeType"),
                    "modified_time": item.get("modifiedTime"),
                    "size": int(item["size"]) if item.get("size") is not None else None,
                }
            )
    folders.sort(key=lambda f: f["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    return {"folders": folders, "files": files}


# --- poller / scan inbox ------------------------------------------------------


def scan_once(db: Session) -> dict:
    """One poll of the scans folder: upsert scan_inbox by drive_file_id.

    The listing is always FULL, so UNKNOWN drive_file_ids are upserted
    regardless of their modifiedTime — a file moved into the folder keeps its
    old timestamp and must still appear. The last_poll_at minus 5-minute
    overlap cutoff (the overlap absorbs clock skew between Drive and this PC)
    only optimizes away the metadata REFRESH of already-known rows. Existing
    rows KEEP their status (a re-modified ignored scan stays ignored).
    last_poll_at advances on every run.
    """
    account = get_account(db)
    if not account.scans_folder_id:
        raise RuleViolation("No scans folder configured")
    client = get_drive_client(db)

    cutoff = None
    if account.last_poll_at:
        cutoff = _parse_rfc3339(account.last_poll_at) - POLL_OVERLAP

    known = set(db.scalars(select(ScanInbox.drive_file_id)))
    new = seen = 0
    for item in client.list_children(account.scans_folder_id):
        if item.get("mimeType") == FOLDER_MIME:
            continue
        seen += 1
        modified = item.get("modifiedTime")
        size = int(item["size"]) if item.get("size") is not None else None
        if item["id"] not in known:
            # ON CONFLICT DO NOTHING: the interval poll job can insert the same
            # drive_file_id between our `known` read and this statement (manual
            # scan-now racing the scheduler) — losing that race must skip the
            # row, not 500 on the UNIQUE constraint. rowcount is 0 on conflict.
            inserted = db.execute(
                sqlite_insert(ScanInbox)
                .values(
                    drive_file_id=item["id"],
                    name=item["name"],
                    mime=item.get("mimeType"),
                    modified_time=modified,
                    md5=item.get("md5Checksum"),
                    size_bytes=size,
                    discovered_at=utcnow(),
                    status="new",
                )
                .on_conflict_do_nothing(index_elements=["drive_file_id"])
            ).rowcount
            new += inserted
            continue
        if cutoff is not None and modified and _parse_rfc3339(modified) < cutoff:
            continue  # known row, unmodified since the last poll — skip refresh
        row = db.scalar(select(ScanInbox).where(ScanInbox.drive_file_id == item["id"]))
        if row is None:  # pragma: no cover — deleted between the two reads
            continue
        row.name = item["name"]
        row.mime = item.get("mimeType")
        row.modified_time = modified
        row.md5 = item.get("md5Checksum")
        row.size_bytes = size
    account.last_poll_at = _format_rfc3339(utcnow())
    db.commit()
    return {"new": new, "seen": seen}


def poll_job() -> None:
    """Interval-job body: silently no-op unless connected + folder configured;
    never lets an error escape into APScheduler."""
    if not is_connected():
        return
    from app.database import get_sessionmaker

    db = get_sessionmaker()()
    try:
        if not get_account(db).scans_folder_id:
            return
        scan_once(db)
    except Exception:
        logger.exception("Drive scans-folder poll failed")
    finally:
        db.close()


def list_inbox(db: Session, status: str | None = None) -> list[ScanInbox]:
    stmt = select(ScanInbox).order_by(ScanInbox.discovered_at.desc(), ScanInbox.id.desc())
    if status is not None:
        stmt = stmt.where(ScanInbox.status == status)
    return list(db.scalars(stmt))


def _get_row(db: Session, row_id: int) -> ScanInbox:
    row = db.get(ScanInbox, row_id)
    if row is None:
        raise NotFoundError(f"Scan inbox row {row_id} not found")
    return row


def ignore_row(db: Session, row_id: int) -> ScanInbox:
    row = _get_row(db, row_id)
    if row.status == "attached":
        raise RuleViolation("Inbox item is already attached")
    row.status = "ignored"
    db.commit()
    return row


def _get_entity(db: Session, entity_id: int) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise NotFoundError(f"Entity {entity_id} not found")
    return entity


def attach_inbox_row(
    db: Session, row_id: int, entity_id: int, title: str | None = None
) -> tuple[ScanInbox, Attachment]:
    """Triage 'attach': drive_link attachment on the entity + row marked
    attached, one transaction. 409 when the row is already attached. Without an
    explicit title the Drive file name is used so lists show a real name."""
    row = _get_row(db, row_id)
    if row.status == "attached":
        raise RuleViolation("Inbox item is already attached")
    entity = _get_entity(db, entity_id)
    attachment = Attachment(
        entity_id=entity.id,
        type="drive_link",
        title=title or row.name,
        mime=row.mime,
        byte_size=row.size_bytes,
        drive_file_id=row.drive_file_id,
        drive_name=row.name,
        drive_mime=row.mime,
        drive_modified_time=row.modified_time,
        drive_md5=row.md5,
        drive_status="ok",
    )
    db.add(attachment)
    db.flush()
    row.status = "attached"
    row.attachment_id = attachment.id
    db.commit()
    return row, attachment


def attach_file(
    db: Session, entity_id: int, file_id: str, title: str | None = None
) -> Attachment:
    """Attach ANY Drive file (picked via /drive/browse) to an entity.
    Duplicate file_id on the SAME entity -> 409; a matching still-new inbox row
    is marked attached too so the triage list stays coherent. Without an
    explicit title the Drive file name is used so lists show a real name."""
    entity = _get_entity(db, entity_id)
    duplicate = db.scalar(
        select(Attachment.id)
        .where(Attachment.entity_id == entity.id, Attachment.drive_file_id == file_id)
        .limit(1)
    )
    if duplicate is not None:
        raise RuleViolation("This Drive file is already attached to the entity")
    client = get_drive_client(db)
    meta = client.file_metadata(file_id)
    if meta is None:
        raise NotFoundError("Drive file not found (or trashed)")
    attachment = Attachment(
        entity_id=entity.id,
        type="drive_link",
        title=title or meta["name"],
        mime=meta.get("mimeType"),
        byte_size=int(meta["size"]) if meta.get("size") is not None else None,
        drive_file_id=meta["id"],
        drive_name=meta["name"],
        drive_mime=meta.get("mimeType"),
        drive_modified_time=meta.get("modifiedTime"),
        drive_md5=meta.get("md5Checksum"),
        drive_status="ok",
    )
    db.add(attachment)
    db.flush()
    row = db.scalar(select(ScanInbox).where(ScanInbox.drive_file_id == file_id))
    if row is not None and row.status == "new":
        row.status = "attached"
        row.attachment_id = attachment.id
    db.commit()
    return attachment


# --- thumbnail cache ----------------------------------------------------------


def cached_thumb_url(file_id: str) -> str | None:
    """'/media/drive-cache/{fileId}/{md5}.jpg' URL for an already-cached
    thumbnail, else None."""
    folder = _thumb_dir(file_id)
    if not folder.is_dir():
        return None
    for path in folder.glob("*.jpg"):
        return f"/media/drive-cache/{folder.name}/{path.name}"
    return None


def _known_md5(db: Session, file_id: str) -> str | None:
    """The md5 we currently believe the file has — from any drive_link
    attachment row, falling back to the scan inbox; None when untracked."""
    md5 = db.scalar(
        select(Attachment.drive_md5)
        .where(Attachment.drive_file_id == file_id, Attachment.drive_md5.is_not(None))
        .limit(1)
    )
    if md5:
        return md5
    return db.scalar(select(ScanInbox.md5).where(ScanInbox.drive_file_id == file_id))


def ensure_thumbnail(db: Session, file_id: str) -> dict:
    """Ensure the thumbnail cache for a Drive file: on a cache hit whose md5
    still matches what we track for the file, return the URL with NO client
    call; a stale hit (tracked md5 drifted) drops the old file, and any fetch
    gets a FRESH thumbnailLink via metadata (the link itself is short-lived and
    never stored), downloads the bytes and saves drive-cache/{fileId}/{md5}.jpg.
    {'url': None} when Drive offers no thumbnail."""
    _validate_file_id(file_id)
    cached = cached_thumb_url(file_id)
    if cached is not None:
        expected = _known_md5(db, file_id)
        if expected is None or _safe_name(expected) == Path(cached).stem:
            return {"url": cached}
        delete_cached_thumbs(file_id)  # md5 drifted -> the cached thumb is stale
    client = get_drive_client(db)
    meta = client.file_metadata(file_id)
    if meta is None:
        raise NotFoundError("Drive file not found (or trashed)")
    return {"url": _download_thumb(client, meta)}


def _download_thumb(client: DriveClient, meta: dict) -> str | None:
    link = meta.get("thumbnailLink")
    if not link:
        return None
    data = client.download_thumbnail(link)
    if not data:
        return None
    md5 = meta.get("md5Checksum") or hashlib.md5(data).hexdigest()
    folder = _thumb_dir(meta["id"])
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{_safe_name(md5)}.jpg"
    (folder / name).write_bytes(data)
    return f"/media/drive-cache/{folder.name}/{name}"


def delete_cached_thumbs(file_id: str) -> None:
    """Best-effort removal of one file's cached thumbs (cache is regenerable).
    Also called when a drive_link attachment is deleted."""
    folder = _thumb_dir(file_id)
    if not folder.is_dir():
        return
    for path in folder.glob("*.jpg"):
        path.unlink(missing_ok=True)
    try:
        folder.rmdir()  # leave the dir alone if anything non-jpg remains
    except OSError:
        pass


def _refresh_cached_thumb(client: DriveClient, file_id: str, meta: dict) -> None:
    """A changed file's cached thumb is stale: drop it and (if one was cached
    before) re-download against the new content."""
    if cached_thumb_url(file_id) is None:
        return  # never cached — nothing to refresh
    delete_cached_thumbs(file_id)
    _download_thumb(client, meta)


# --- reconciliation -----------------------------------------------------------


def reconcile(db: Session) -> dict:
    """For every DISTINCT drive_file_id across attachments: refresh the
    denormalized name/mime/modified/md5 from fresh metadata; 404/trashed ->
    drive_status 'missing'; md5 changed -> 'changed' (+ cached thumb refresh).
    'changed' is a one-cycle flag: the md5 refresh means the NEXT reconcile
    reports the file as ok again. Counts are per distinct file."""
    client = get_drive_client(db)
    file_ids = list(
        db.scalars(
            select(Attachment.drive_file_id)
            .where(Attachment.type == "drive_link")
            .distinct()
        )
    )
    counts = {"ok": 0, "missing": 0, "changed": 0}
    for file_id in file_ids:
        rows = list(db.scalars(select(Attachment).where(Attachment.drive_file_id == file_id)))
        meta = client.file_metadata(file_id)
        if meta is None:
            for row in rows:
                row.drive_status = "missing"
            counts["missing"] += 1
            continue
        changed = any(row.drive_md5 != meta.get("md5Checksum") for row in rows)
        for row in rows:
            row.drive_name = meta["name"]
            row.drive_mime = meta.get("mimeType")
            row.drive_modified_time = meta.get("modifiedTime")
            row.drive_md5 = meta.get("md5Checksum")
            row.drive_status = "changed" if changed else "ok"
        counts["changed" if changed else "ok"] += 1
        if changed:
            _refresh_cached_thumb(client, file_id, meta)
    db.commit()
    return counts


# --- backup push --------------------------------------------------------------


def _ensure_backup_folder(db: Session, client: DriveClient, account: DriveAccount) -> str:
    """'Archiviator Backups' folder, ensured ONCE — the id is cached on the
    drive_account row and reused until an upload proves it gone (see
    upload_snapshot, which drops the cache and re-ensures on FolderGoneError)."""
    if account.backup_folder_id:
        return account.backup_folder_id
    folder_id = client.ensure_folder(BACKUP_FOLDER_NAME, parent=None)
    account.backup_folder_id = folder_id
    db.commit()
    return folder_id


def _prune_drive_backups(client: DriveClient, folder_id: str) -> None:
    """Keep the newest DRIVE_BACKUP_KEEP 'db-*.db' files; the timestamp in the
    name makes lexicographic order chronological. Deletes are PERMANENT (the
    client's delete bypasses trash) — acceptable for our own backup files."""
    snapshots = [
        item
        for item in client.list_children(folder_id)
        if item.get("mimeType") != FOLDER_MIME
        and item["name"].startswith("db-")
        and item["name"].endswith(".db")
    ]
    snapshots.sort(key=lambda item: item["name"])
    excess = snapshots[:-DRIVE_BACKUP_KEEP] if len(snapshots) > DRIVE_BACKUP_KEEP else []
    for stale in excess:
        client.delete_file(stale["id"])


def upload_snapshot(db: Session, snapshot_name: str) -> dict:
    """Upload one local snapshot file to the Drive backup folder, then prune."""
    path = backup.backups_dir(get_settings().data_dir) / snapshot_name
    if not path.is_file():
        raise NotFoundError(f"Backup snapshot {snapshot_name} not found")
    client = get_drive_client(db)
    account = get_account(db)
    folder_id = _ensure_backup_folder(db, client, account)
    try:
        uploaded = client.upload_file(str(path), folder_id, filename=path.name)
    except FolderGoneError:
        # The cached backup folder was deleted on Drive: drop the cached id,
        # re-ensure the folder once and retry the upload once.
        account.backup_folder_id = None
        db.commit()
        folder_id = _ensure_backup_folder(db, client, account)
        uploaded = client.upload_file(str(path), folder_id, filename=path.name)
    _prune_drive_backups(client, folder_id)
    account.last_backup_upload_at = _format_rfc3339(utcnow())
    db.commit()
    return {"file": path.name, "drive_file_id": uploaded["id"]}


def backup_now(db: Session) -> dict:
    """POST /drive/backup-now: fresh local snapshot (the exact nightly body),
    then push it to Drive immediately."""
    result = backup.run_backup(get_settings().data_dir)
    return upload_snapshot(db, result["file"])


def run_nightly(backup_result: dict) -> None:
    """Nightly Drive tasks, run AFTER the local backup: push the fresh snapshot
    (when enabled) and reconcile drive_link attachments. Each step is guarded —
    a Drive hiccup must never fail the local backup job."""
    if not is_connected():
        return
    from app.database import get_sessionmaker

    db = get_sessionmaker()()
    try:
        if get_account(db).backup_upload_enabled:
            try:
                upload_snapshot(db, backup_result["file"])
            except Exception:
                logger.exception("Nightly Drive backup upload failed")
        try:
            reconcile(db)
        except Exception:
            logger.exception("Nightly Drive reconciliation failed")
    finally:
        db.close()
