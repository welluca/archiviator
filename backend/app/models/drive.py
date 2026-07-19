"""M9 Google Drive ORM models: the singleton account/config row and the scan inbox.

drive_account is a single-row table (id = 1 enforced by CHECK, seeded by
migration 0008) holding connection state + configuration. Timestamps that pair
with Drive's RFC3339 modifiedTime strings (last_poll_at, last_backup_upload_at)
are TEXT on purpose so they compare against Drive values without conversion.

scan_inbox mirrors the scans folder: one row per discovered Drive file,
upserted by drive_file_id; status tracks the triage decision and attachment_id
links to the drive_link attachment once attached (SET NULL if that attachment
is later deleted — the row keeps its 'attached' status as history).
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.dt import utcnow

SCAN_STATUSES = ("new", "attached", "ignored")


class DriveAccount(Base):
    __tablename__ = "drive_account"
    __table_args__ = (CheckConstraint("id = 1", name="ck_drive_account_single"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(Text)
    scans_folder_id: Mapped[str | None] = mapped_column(Text)
    scans_folder_name: Mapped[str | None] = mapped_column(Text)
    backup_folder_id: Mapped[str | None] = mapped_column(Text)
    poll_interval_min: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    backup_upload_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    last_poll_at: Mapped[str | None] = mapped_column(Text)
    last_backup_upload_at: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<DriveAccount email={self.email!r}>"


class ScanInbox(Base):
    __tablename__ = "scan_inbox"
    __table_args__ = (
        CheckConstraint("status IN ('new','attached','ignored')", name="ck_scan_inbox_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    drive_file_id: Mapped[str] = mapped_column(Text, unique=True, index=True)
    name: Mapped[str] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(Text)
    modified_time: Mapped[str | None] = mapped_column(Text)
    md5: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(Text, default="new", server_default="new", index=True)
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachment.id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        return f"<ScanInbox {self.id} {self.name!r} {self.status}>"
