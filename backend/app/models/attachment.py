"""Attachment ORM model: photos/documents stored content-addressed on disk, plus
Google Drive links (M4 — columns exist now so the table never needs a rebuild).

file_path/display_path/thumb_path are POSIX-style relative paths under data_dir
(e.g. 'attachments/ab/abcd….jpg', 'derived/abcd…_320.jpg'). content_hash is the
sha256 of the PROCESSED original bytes — several rows may share one hash (dedup),
so on-disk files are only unlinked when the last referencing row goes away.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.dt import utcnow

ATTACHMENT_TYPES = ("photo", "document", "drive_link")


class Attachment(Base):
    __tablename__ = "attachment"
    __table_args__ = (
        CheckConstraint(
            "type IN ('photo','document','drive_link')", name="ck_attachment_type"
        ),
        CheckConstraint(
            "drive_status IN ('ok','missing','changed')", name="ck_attachment_drive_status"
        ),
        # A row is either a stored file (photo/document) or a drive link, never both.
        CheckConstraint(
            "(type IN ('photo','document') AND file_path IS NOT NULL AND drive_file_id IS NULL)"
            " OR (type = 'drive_link' AND drive_file_id IS NOT NULL AND file_path IS NULL)",
            name="ck_attachment_storage",
        ),
        Index(
            "ix_attachment_content_hash",
            "content_hash",
            sqlite_where=text("content_hash IS NOT NULL"),
        ),
        Index(
            "ix_attachment_drive_file_id",
            "drive_file_id",
            sqlite_where=text("drive_file_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    file_path: Mapped[str | None] = mapped_column(Text)
    thumb_path: Mapped[str | None] = mapped_column(Text)
    display_path: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    drive_file_id: Mapped[str | None] = mapped_column(Text)
    drive_name: Mapped[str | None] = mapped_column(Text)
    drive_mime: Mapped[str | None] = mapped_column(Text)
    drive_modified_time: Mapped[str | None] = mapped_column(Text)
    drive_md5: Mapped[str | None] = mapped_column(Text)
    drive_status: Mapped[str] = mapped_column(Text, default="ok", server_default="ok")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def __repr__(self) -> str:
        return f"<Attachment {self.id} {self.type} entity={self.entity_id}>"
