"""Media pipeline: content-addressed storage of processed uploads under data_dir.

Layout (all paths stored relative, POSIX-style):
    attachments/{hash[:2]}/{sha256}.jpg|.png|.pdf   processed original
    derived/{sha256}_1600.jpg, {sha256}_320.jpg     photo derivatives (regenerable)

The sha256 is computed over the PROCESSED bytes, so identical uploads (and
re-uploads of the same source) land on the same files. Writes are if-absent;
deletes go through delete_files_if_unreferenced so dedup'd rows never pull the
files out from under each other.

Photo pipeline: EXIF-transpose, flatten alpha onto white, cap the long edge at
3000px (LANCZOS), save JPEG q87 with EXIF stripped. A PNG stays PNG only if it
had no alpha and needed no resize. Derivatives are always JPEG q82 and are only
ever downscaled. PDFs are stored verbatim with no derivatives.
"""

import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.attachment import Attachment

pillow_heif.register_heif_opener()

MAX_UPLOAD = 30 * 1024 * 1024
ORIGINAL_CAP = 3000
DISPLAY_SIZE = 1600
THUMB_SIZE = 320
JPEG_QUALITY = 87
DERIVED_QUALITY = 82


class MediaError(Exception):
    """Base class for media domain errors; str(exc) becomes the HTTP detail."""


class UnsupportedMediaError(MediaError):
    """Upload is neither an image nor a PDF -> 415."""


class FileTooLargeError(MediaError):
    """Upload exceeds MAX_UPLOAD -> 413."""


@dataclass(frozen=True)
class ProcessedPhoto:
    file_path: str
    display_path: str
    thumb_path: str
    content_hash: str
    mime: str
    byte_size: int
    width: int
    height: int


@dataclass(frozen=True)
class ProcessedDocument:
    file_path: str
    content_hash: str
    mime: str
    byte_size: int


def media_root() -> Path:
    return get_settings().data_dir


def attachments_dir() -> Path:
    return media_root() / "attachments"


def derived_dir() -> Path:
    return media_root() / "derived"


def _original_rel(content_hash: str, ext: str) -> str:
    return f"attachments/{content_hash[:2]}/{content_hash}{ext}"


def _derived_rel(content_hash: str, size: int) -> str:
    return f"derived/{content_hash}_{size}.jpg"


def _write_if_absent(rel_path: str, data: bytes) -> None:
    path = media_root() / rel_path
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info
    )


def _flatten_rgb(img: Image.Image) -> Image.Image:
    """Flatten any alpha onto a white background; otherwise plain RGB convert."""
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img if img.mode == "RGB" else img.convert("RGB")


def _encode_derivative(rgb: Image.Image, size: int) -> bytes:
    scaled = rgb.copy()
    scaled.thumbnail((size, size), Image.Resampling.LANCZOS)  # never upscales
    buf = io.BytesIO()
    scaled.save(buf, "JPEG", quality=DERIVED_QUALITY)
    return buf.getvalue()


def process_photo(data: bytes) -> ProcessedPhoto:
    """Run the photo pipeline and persist original + derivatives (write-if-absent)."""
    try:
        img = Image.open(io.BytesIO(data))
        source_format = img.format
        img.load()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,  # huge pixel counts subclass Exception, not OSError
        OSError,
        ValueError,
    ) as exc:
        raise UnsupportedMediaError("Unsupported file type (not an image or PDF)") from exc

    img = ImageOps.exif_transpose(img)

    keep_png = (
        source_format == "PNG"
        and not _has_alpha(img)
        and max(img.size) <= ORIGINAL_CAP
    )
    if keep_png:
        # No alpha and no resize needed: re-encode as PNG (drops EXIF/ancillary data).
        buf = io.BytesIO()
        img.save(buf, "PNG")
        ext, mime = ".png", "image/png"
    else:
        img = _flatten_rgb(img)
        if max(img.size) > ORIGINAL_CAP:
            scale = ORIGINAL_CAP / max(img.size)
            img = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_QUALITY)  # no exif kwarg -> EXIF stripped
        ext, mime = ".jpg", "image/jpeg"

    original = buf.getvalue()
    content_hash = hashlib.sha256(original).hexdigest()
    file_path = _original_rel(content_hash, ext)
    _write_if_absent(file_path, original)

    rgb = _flatten_rgb(img)
    display_path = _derived_rel(content_hash, DISPLAY_SIZE)
    thumb_path = _derived_rel(content_hash, THUMB_SIZE)
    _write_if_absent(display_path, _encode_derivative(rgb, DISPLAY_SIZE))
    _write_if_absent(thumb_path, _encode_derivative(rgb, THUMB_SIZE))

    return ProcessedPhoto(
        file_path=file_path,
        display_path=display_path,
        thumb_path=thumb_path,
        content_hash=content_hash,
        mime=mime,
        byte_size=len(original),
        width=img.width,
        height=img.height,
    )


def process_document(data: bytes, mime: str = "application/pdf") -> ProcessedDocument:
    """Store a document verbatim (no derivatives, no width/height)."""
    content_hash = hashlib.sha256(data).hexdigest()
    file_path = _original_rel(content_hash, ".pdf")
    _write_if_absent(file_path, data)
    return ProcessedDocument(
        file_path=file_path, content_hash=content_hash, mime=mime, byte_size=len(data)
    )


def ensure_derivatives(content_hash: str) -> bool:
    """Regenerate missing derived files for a stored photo original. Returns True
    if the original exists (derivatives now present), False if it is gone."""
    matches = [
        p
        for p in (attachments_dir() / content_hash[:2]).glob(f"{content_hash}.*")
        if p.suffix != ".tmp"  # a crashed _write_if_absent can leave partial .tmp files
    ]
    if not matches:
        return False
    missing = [
        size
        for size in (DISPLAY_SIZE, THUMB_SIZE)
        if not (media_root() / _derived_rel(content_hash, size)).exists()
    ]
    if missing:
        rgb = _flatten_rgb(Image.open(matches[0]))
        for size in missing:
            _write_if_absent(_derived_rel(content_hash, size), _encode_derivative(rgb, size))
    return True


def delete_files_if_unreferenced(
    db: Session, content_hash: str | None, exclude_attachment_id: int | None = None
) -> None:
    """Unlink the original + derived files iff no attachment row still references
    the hash (dedup'd uploads share files; the last row out turns off the lights)."""
    if content_hash is None:
        return
    stmt = select(func.count(Attachment.id)).where(Attachment.content_hash == content_hash)
    if exclude_attachment_id is not None:
        stmt = stmt.where(Attachment.id != exclude_attachment_id)
    if db.scalar(stmt):
        return
    # Best-effort: on Windows an open handle (concurrent /media stream, antivirus,
    # indexer) raises PermissionError; the row is already gone, and an orphaned
    # file is harmless, so never fail the request over it.
    for path in (attachments_dir() / content_hash[:2]).glob(f"{content_hash}.*"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    for size in (DISPLAY_SIZE, THUMB_SIZE):
        try:
            (media_root() / _derived_rel(content_hash, size)).unlink(missing_ok=True)
        except OSError:
            pass
