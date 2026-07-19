"""In-process APScheduler wiring (M6): the nightly 03:30 backup job.

The scheduler is built and started in the FastAPI lifespan ONLY when
settings.scheduler_enabled is true (tests disable it via env in conftest).
The job body is a plain importable function so tests and the /admin/backup-now
endpoint exercise the exact same code path.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.services import backup

NIGHTLY_JOB_ID = "nightly-backup"


def nightly_backup() -> dict:
    """The 03:30 job body: snapshot + prune. Reads settings at call time."""
    from app.config import get_settings

    return backup.run_backup(get_settings().data_dir)


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    """Scheduler with the nightly backup registered (not started)."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        nightly_backup,
        CronTrigger(hour=3, minute=30),
        id=NIGHTLY_JOB_ID,
        name="Nightly database backup",
        replace_existing=True,
    )
    return scheduler
