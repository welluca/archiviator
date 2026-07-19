"""Backup service (M6): WAL-safe online SQLite snapshots via VACUUM INTO.

Snapshots run on a DEDICATED sqlite3 connection (never the app engine) so they
cannot interfere with the ORM session's transaction state. Files land in
{data_dir}/backups/db-YYYYMMDD-HHMMSS.db and are pruned to the newest KEEP.
"""

import os
import sqlite3
from pathlib import Path

from app.utils.dt import utcnow

KEEP = 14
DB_FILENAME = "archiviator.db"


def snapshot_to(db_path: Path, target: Path) -> None:
    """VACUUM INTO `target` on a dedicated connection (consistent even mid-WAL),
    then fsync so the snapshot survives a crash right after."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()  # VACUUM INTO refuses to overwrite
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
    finally:
        conn.close()
    with open(target, "rb+") as fh:
        fh.flush()
        os.fsync(fh.fileno())


def backups_dir(data_dir: Path) -> Path:
    return data_dir / "backups"


def run_backup(data_dir: Path) -> dict:
    """Snapshot the live database and prune old backups; the nightly job body
    and the /admin/backup-now endpoint both call exactly this."""
    target_dir = backups_dir(data_dir)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    name = f"db-{stamp}.db"
    suffix = 1
    while (target_dir / name).exists():  # same-second reruns must not overwrite
        suffix += 1
        name = f"db-{stamp}-{suffix}.db"
    target = target_dir / name
    snapshot_to(data_dir / DB_FILENAME, target)
    prune_backups(target_dir)
    return {"file": target.name, "bytes": target.stat().st_size}


def prune_backups(target_dir: Path, keep: int = KEEP) -> None:
    """Delete all but the newest `keep` snapshot files."""
    files = sorted(
        target_dir.glob("db-*.db"), key=lambda p: (p.stat().st_mtime, p.name)
    )
    for stale in files[:-keep] if len(files) > keep else []:
        stale.unlink()


def list_backups(data_dir: Path) -> list[dict]:
    """[{file, bytes, created_at}] newest first. created_at is timezone-AWARE
    UTC so it serializes with an offset (+00:00) and `new Date()` parses it
    correctly in the frontend (a naive string would be read as local time)."""
    from datetime import datetime, timezone

    target_dir = backups_dir(data_dir)
    if not target_dir.exists():
        return []
    files = sorted(
        target_dir.glob("db-*.db"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    return [
        {
            "file": f.name,
            "bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc),
        }
        for f in files
    ]
