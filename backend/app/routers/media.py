"""Unauthenticated media serving for stored attachments, derivatives and
floor-plan images.

Deliberate tradeoff: /media is NOT Bearer-authed. URLs are content-addressed
(sha256 of the processed bytes), so a URL is itself an unguessable capability
token, and the app runs single-user on a private tailnet — <img> tags and PDF
viewers then work without auth plumbing. Only files under data_dir/attachments,
data_dir/derived and data_dir/floorplans (M8 floor plans share the same
content-addressed tradeoff) are ever served (path-traversal guarded);
everything else in data_dir (DB, secret.key) is unreachable.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.config import get_settings

router = APIRouter()

CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.api_route("/media/{path:path}", methods=["GET", "HEAD"])
async def serve_media(path: str):
    root = get_settings().data_dir.resolve()
    try:
        target = (root / path).resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # Traversal guard: after resolution the target must sit inside one of the
    # servable subtrees — '..' segments or absolute paths land outside.
    # drive-cache/ (M9 Drive thumbnails) shares the same tradeoff: filenames are
    # {fileId}-{md5}.jpg and Drive fileIds are not secrets on a private tailnet.
    allowed = (
        root / "attachments",
        root / "derived",
        root / "floorplans",
        root / "drive-cache",
    )
    if not any(target.is_relative_to(base) for base in allowed) or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(target, headers={"Cache-Control": CACHE_CONTROL})
