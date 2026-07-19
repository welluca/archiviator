"""Google Drive OAuth 2.0 (user credentials) for Archiviator.

Provenance: adapted from the working
c:/Users/Luca/Documents/__site/gdriveexchanger/shared/gdrive/auth.py.
Changes for Archiviator:
- silent credential loading (load/refresh) is SPLIT from the interactive
  InstalledAppFlow so the API server can refresh tokens without ever opening a
  browser; the browser flow runs only from POST /drive/connect (worker thread);
- token path + client-secret path come from OUR settings/meta, never a path
  derived from the secret's directory; the client secret is only ever READ in
  place — never copied or moved;
- token contents are never logged.

Scope is the FULL 'drive' scope: read access for the scanned-documents inbox
plus write access for backup uploads. NOTE: the Google Cloud consent screen for
the OAuth client must be 'In production' — a client left 'In testing' issues
refresh tokens that die after 7 days (surfaced as a UI hint; not enforceable
in code).
"""

import logging
from pathlib import Path

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


def load_credentials(token_path: Path) -> Credentials | None:
    """Silently load credentials from token.json, refreshing when expired.

    Returns None (never opens a browser) when there is no token, the token is
    unreadable, or the refresh fails — a stale token file is deleted so the
    next interactive connect starts clean.
    """
    if not token_path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except (ValueError, OSError):
        logger.warning("Unreadable Drive token file; deleting it")
        token_path.unlink(missing_ok=True)
        return None

    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            logger.info("Refreshing expired Drive token")
            creds.refresh(Request())
        except (RefreshError, GoogleAuthError, OSError):
            logger.warning("Drive token refresh failed; deleting stale token")
            token_path.unlink(missing_ok=True)
            return None
        save_token(creds, token_path)
        return creds
    return None


def run_installed_flow(credentials_file: str | Path, token_path: Path) -> Credentials:
    """BLOCKING interactive OAuth: opens a browser ON THIS PC (the server PC —
    which is fine, server == Luca's desktop). Saves token.json on success.
    Call from a worker thread, never from the event loop.
    """
    cred_path = Path(credentials_file)
    if not cred_path.exists():
        raise FileNotFoundError(f"Google client secret file not found: {credentials_file}")
    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
    creds = flow.run_local_server(port=0)
    logger.info("Google Drive authentication successful")
    save_token(creds, token_path)
    return creds


def save_token(creds: Credentials, token_path: Path) -> None:
    """Persist the token JSON (contents deliberately never logged)."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Drive token saved to %s", token_path)


def build_service(creds: Credentials) -> Resource:
    """Drive v3 service resource (discovery cache off: avoids oauth2client noise)."""
    return build("drive", "v3", credentials=creds, cache_discovery=False)
