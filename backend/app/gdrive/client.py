"""High-level Google Drive client implementing the DriveClient protocol.

Provenance: adapted from the working
c:/Users/Luca/Documents/__site/gdriveexchanger/shared/gdrive/client.py.
Kept from the original: resumable uploads with exponential backoff on
429/500/503, folder find-or-create with an in-memory cache, permanent
files().delete. Changes for Archiviator: the surface is trimmed and reshaped
to the DriveClient protocol in app/services/drive.py (list_children,
file_metadata, download_thumbnail, upload_file, ensure_folder, delete_file,
user_email); metadata fetches carry thumbnailLink/trashed for the scan inbox
and reconciliation.

delete_file uses files().delete which BYPASSES the trash — acceptable here
because Archiviator only ever deletes its own pruned backup snapshots.
"""

import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.gdrive.auth import build_service
from app.services.drive import FolderGoneError

logger = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"

FILE_FIELDS = "id, name, mimeType, modifiedTime, md5Checksum, size, trashed, thumbnailLink"


class GDriveClient:
    """Real Drive API client (network). Tests always substitute a fake via
    app.services.drive.get_drive_client — no test may construct this."""

    def __init__(
        self,
        creds: Credentials,
        max_retries: int = 3,
        retry_delay: int = 10,
        chunk_size_mb: int = 50,
    ):
        self.creds = creds
        self.service = build_service(creds)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.chunk_size = chunk_size_mb * 1024 * 1024
        self._folder_cache: dict[str, str] = {}

    # --- listing / metadata ---------------------------------------------------

    def list_children(self, folder_id: str) -> list[dict]:
        """All non-trashed children (files AND folders) of a folder, paged."""
        query = f"'{folder_id}' in parents and trashed = false"
        results: list[dict] = []
        page_token = None
        while True:
            resp = (
                self.service.files()
                .list(
                    q=query,
                    fields=f"nextPageToken, files({FILE_FIELDS})",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return results

    def file_metadata(self, file_id: str) -> dict | None:
        """Fresh metadata for one file; None when the file is 404 or trashed."""
        try:
            meta = self.service.files().get(fileId=file_id, fields=FILE_FIELDS).execute()
        except HttpError as exc:
            if exc.resp.status == 404:
                return None
            raise
        if meta.get("trashed"):
            return None
        return meta

    def download_thumbnail(self, url: str) -> bytes | None:
        """Fetch thumbnail bytes from a (short-lived) thumbnailLink. The link is
        used immediately and never stored."""
        req = urllib.request.Request(url)
        if self.creds and self.creds.token:
            req.add_header("Authorization", f"Bearer {self.creds.token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("Thumbnail download failed: %s", exc)
            return None

    # --- folders --------------------------------------------------------------

    def ensure_folder(self, name: str, parent: str | None = None) -> str:
        """Find-or-create a folder by name under `parent` (None = My Drive root)."""
        cache_key = f"{parent or 'root'}:{name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        query = f"name = '{name}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        if parent:
            query += f" and '{parent}' in parents"
        resp = self.service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
        files = resp.get("files", [])
        if files:
            folder_id = files[0]["id"]
        else:
            metadata: dict = {"name": name, "mimeType": FOLDER_MIME}
            if parent:
                metadata["parents"] = [parent]
            folder = self.service.files().create(body=metadata, fields="id").execute()
            folder_id = folder["id"]
            logger.info("Created Drive folder: %s (%s)", name, folder_id)
        self._folder_cache[cache_key] = folder_id
        return folder_id

    # --- upload / delete ------------------------------------------------------

    def upload_file(
        self, local_path: str, parent_folder_id: str, filename: str | None = None
    ) -> dict:
        """Resumable upload with exponential backoff (kept from gdriveexchanger).
        Returns {'id', 'name', 'size', 'md5Checksum'}."""
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")
        name = filename or path.name
        metadata = {"name": name, "parents": [parent_folder_id]}
        media = MediaFileUpload(str(path), resumable=True, chunksize=self.chunk_size)

        last_error: HttpError | None = None
        for attempt in range(self.max_retries):
            try:
                request = self.service.files().create(
                    body=metadata, media_body=media, fields="id, name, size, md5Checksum"
                )
                response = None
                while response is None:
                    upload_status, response = request.next_chunk()
                    if upload_status:
                        logger.debug(
                            "Upload %s: %d%%", name, int(upload_status.progress() * 100)
                        )
                result = {
                    "id": response["id"],
                    "name": response["name"],
                    "size": int(response.get("size", 0)),
                    "md5Checksum": response.get("md5Checksum"),
                }
                logger.info("Uploaded to Drive: %s (%d bytes)", name, result["size"])
                return result
            except HttpError as exc:
                last_error = exc
                if exc.resp.status == 404:
                    # The parent folder no longer exists (deleted on Drive) —
                    # surface the protocol error so the caller can drop its
                    # cached folder id, re-ensure and retry.
                    raise FolderGoneError(
                        f"Drive parent folder {parent_folder_id} not found"
                    ) from exc
                if exc.resp.status in (429, 500, 503) and attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2**attempt)
                    logger.warning(
                        "Upload retry %d/%d for %s, waiting %ds",
                        attempt + 1,
                        self.max_retries,
                        name,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error("Upload failed for %s: %s", name, exc)
                    raise
        raise last_error  # pragma: no cover — loop always returns or raises

    def delete_file(self, file_id: str) -> bool:
        """PERMANENT delete (files().delete bypasses the trash) — used only to
        prune our own backup snapshots. True when gone (404 counts as gone)."""
        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info("Deleted Drive file: %s", file_id)
            return True
        except HttpError as exc:
            if exc.resp.status == 404:
                return True
            logger.error("Error deleting Drive file %s: %s", file_id, exc)
            return False

    # --- account --------------------------------------------------------------

    def user_email(self) -> str | None:
        """The connected account's email (shown on the /drive page)."""
        try:
            about = self.service.about().get(fields="user(emailAddress)").execute()
            return about.get("user", {}).get("emailAddress")
        except HttpError as exc:
            logger.warning("about().get failed: %s", exc)
            return None
