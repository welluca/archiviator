"""SQLAlchemy 2.0 engine/session bootstrap for the Archiviator SQLite database."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


# Lazily initialized so tests can point ARCHIVIATOR_DATA_DIR elsewhere before first use.
_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    """Create (once) and return the SQLite engine."""
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            settings.db_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            # Disable pysqlite's implicit transaction handling: without this an
            # outermost SAVEPOINT starts the SQLite transaction itself and its
            # RELEASE *commits* it — Session.begin_nested() (CSV import per-row
            # rollback) would silently commit row by row and dry_run could not
            # roll back. SQLAlchemy emits BEGIN via the "begin" hook instead
            # (the documented pysqlite workaround).
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        @event.listens_for(_engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    return _engine


def get_sessionmaker() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db():
    """FastAPI dependency yielding a DB session."""
    db: Session = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Dispose and forget the engine (used by tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def run_migrations() -> None:
    """Programmatically run 'alembic upgrade head' so first run just works."""
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")
