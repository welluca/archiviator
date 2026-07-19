"""In-process APScheduler wiring: the nightly 03:30 backup job (M6) and the
Google Drive scans-folder poll job (M9).

The scheduler is built and started in the FastAPI lifespan ONLY when
settings.scheduler_enabled is true (tests disable it via env in conftest).
Job bodies are plain importable functions so tests and the on-demand endpoints
exercise the exact same code paths.

The poll interval is read from drive_account.poll_interval_min at build time
(migrations have already run in the lifespan); interval changes take effect on
service restart OR immediately via app.services.drive.reschedule_poll, which
the /drive/config PUT calls when app.state.scheduler is present.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings
from app.services import backup

logger = logging.getLogger(__name__)

NIGHTLY_JOB_ID = "nightly-backup"
DRIVE_POLL_JOB_ID = "drive-poll"


def nightly_backup() -> dict:
    """The 03:30 job body: local snapshot + prune, THEN the M9 Drive tasks
    (backup push when enabled, reconciliation) — guarded so a Drive failure
    never fails the local backup. Reads settings at call time."""
    from app.config import get_settings
    from app.services import drive as drive_svc

    result = backup.run_backup(get_settings().data_dir)
    try:
        drive_svc.run_nightly(result)
    except Exception:
        logger.exception("Nightly Drive tasks failed")
    return result


def drive_poll() -> None:
    """Interval job body: poll the Drive scans folder (no-op unless connected
    and a folder is configured — drive.poll_job checks)."""
    from app.services import drive as drive_svc

    drive_svc.poll_job()


def _poll_interval_minutes() -> int:
    """drive_account.poll_interval_min, defaulting to 15 if unreadable."""
    try:
        from app.database import get_sessionmaker
        from app.models.drive import DriveAccount

        db = get_sessionmaker()()
        try:
            account = db.get(DriveAccount, 1)
            return account.poll_interval_min if account else 15
        finally:
            db.close()
    except Exception:
        return 15


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    """Scheduler with the nightly backup + Drive poll registered (not started)."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        nightly_backup,
        CronTrigger(hour=3, minute=30),
        id=NIGHTLY_JOB_ID,
        name="Nightly database backup",
        replace_existing=True,
    )
    scheduler.add_job(
        drive_poll,
        IntervalTrigger(minutes=_poll_interval_minutes()),
        id=DRIVE_POLL_JOB_ID,
        name="Google Drive scans-folder poll",
        replace_existing=True,
    )
    return scheduler
