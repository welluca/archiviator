"""M9 Google Drive tests — ALL against an in-memory FakeDriveClient.

The real client is walled off twice: an autouse fixture replaces the
app.services.drive.get_drive_client factory with one that fails loudly, and the
`fake` fixture then substitutes the FakeDriveClient for tests that need Drive
calls. No test may ever construct app.gdrive.client.GDriveClient (network).

Tests in this module run IN ORDER (shared session client + singleton
drive_account row, same convention as the other modules): unconfigured status
checks come first, then config, connect, and the connected-state features.
The module teardown resets every bit of drive state (token file, meta key,
drive_account row) so later modules see a disconnected app.
"""

import io
import json
import zipfile
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

API = "/api/v1"

FOLDER_MIME = "application/vnd.google-apps.folder"


@pytest.fixture(scope="module")
def auth(client, test_user):
    """One login for the whole module (same pattern as test_tree)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --- fakes & fixtures ---------------------------------------------------------


class FakeDriveClient:
    """In-memory Drive: folders/files keyed by id, thumbnail bytes by URL,
    plus upload/delete logs and a per-method call counter."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.thumbnails: dict[str, bytes] = {}
        self.upload_log: list[dict] = []
        self.delete_log: list[str] = []
        self.calls = Counter()

    # test setup helpers
    def add_folder(self, file_id, name, parent="root"):
        self.items[file_id] = {
            "id": file_id, "name": name, "mimeType": FOLDER_MIME, "parent": parent,
            "modifiedTime": None, "md5Checksum": None, "size": None,
            "thumbnailLink": None, "trashed": False,
        }

    def add_file(
        self, file_id, name, parent="root", mime="application/pdf",
        modified="2026-07-01T10:00:00Z", md5="md5-0", size=1234,
        thumbnail_link=None, trashed=False,
    ):
        self.items[file_id] = {
            "id": file_id, "name": name, "mimeType": mime, "parent": parent,
            "modifiedTime": modified, "md5Checksum": md5,
            "size": str(size) if size is not None else None,
            "thumbnailLink": thumbnail_link, "trashed": trashed,
        }

    def _public(self, item):
        return {
            "id": item["id"], "name": item["name"], "mimeType": item["mimeType"],
            "modifiedTime": item["modifiedTime"], "md5Checksum": item["md5Checksum"],
            "size": item["size"], "thumbnailLink": item["thumbnailLink"],
        }

    # DriveClient protocol
    def list_children(self, folder_id):
        self.calls["list_children"] += 1
        return [
            self._public(i)
            for i in self.items.values()
            if i["parent"] == folder_id and not i["trashed"]
        ]

    def file_metadata(self, file_id):
        self.calls["file_metadata"] += 1
        item = self.items.get(file_id)
        if item is None or item["trashed"]:
            return None
        return self._public(item)

    def download_thumbnail(self, url):
        self.calls["download_thumbnail"] += 1
        return self.thumbnails.get(url)

    def upload_file(self, local_path, parent_folder_id, filename=None):
        self.calls["upload_file"] += 1
        if parent_folder_id not in self.items:
            # Protocol contract: a vanished parent folder surfaces as
            # FolderGoneError (the real client maps HttpError 404 to it).
            from app.services.drive import FolderGoneError

            raise FolderGoneError(f"parent folder {parent_folder_id} not found")
        name = filename or Path(local_path).name
        file_id = f"up{len(self.upload_log) + 1}"
        self.upload_log.append(
            {"local_path": str(local_path), "parent": parent_folder_id, "name": name}
        )
        self.add_file(file_id, name, parent=parent_folder_id,
                      mime="application/octet-stream", md5=f"upmd5-{file_id}",
                      size=Path(local_path).stat().st_size)
        return {"id": file_id, "name": name,
                "size": Path(local_path).stat().st_size, "md5Checksum": f"upmd5-{file_id}"}

    def ensure_folder(self, name, parent=None):
        self.calls["ensure_folder"] += 1
        parent = parent or "root"
        for item in self.items.values():
            if (item["name"] == name and item["mimeType"] == FOLDER_MIME
                    and item["parent"] == parent):
                return item["id"]
        file_id = f"folder-{name}"
        self.add_folder(file_id, name, parent=parent)
        return file_id

    def delete_file(self, file_id):
        self.calls["delete_file"] += 1
        self.delete_log.append(file_id)
        self.items.pop(file_id, None)
        return True

    def user_email(self):
        self.calls["user_email"] += 1
        return "fake@example.com"


@pytest.fixture(autouse=True)
def _no_real_drive_client(monkeypatch):
    """No test may reach the factory without the fake — real construction
    would import google libs and hit the network."""
    from app.services import drive as drive_svc

    def _fail(db):
        raise AssertionError("get_drive_client reached without FakeDriveClient")

    monkeypatch.setattr(drive_svc, "get_drive_client", _fail)


@pytest.fixture()
def fake(monkeypatch):
    from app.services import drive as drive_svc

    client_fake = FakeDriveClient()
    monkeypatch.setattr(drive_svc, "get_drive_client", lambda db: client_fake)
    return client_fake


@pytest.fixture(scope="module", autouse=True)
def _reset_drive_state(client):
    """Leave the app disconnected for later test modules."""
    yield
    from app.models.drive import DriveAccount, ScanInbox  # noqa: F401
    from app.models.meta import Meta
    from app.services import drive as drive_svc

    drive_svc.token_path().unlink(missing_ok=True)
    db = _session()
    try:
        account = db.get(DriveAccount, 1)
        account.scans_folder_id = None
        account.scans_folder_name = None
        account.backup_folder_id = None
        account.backup_upload_enabled = False
        account.email = None
        account.last_poll_at = None
        row = db.get(Meta, drive_svc.META_CREDENTIALS_KEY)
        if row is not None:
            db.delete(row)
        db.commit()
    finally:
        db.close()


# --- helpers ------------------------------------------------------------------


def _session():
    from app.database import get_sessionmaker

    return get_sessionmaker()()


def _data_dir() -> Path:
    from app.config import get_settings

    return get_settings().data_dir


def _write_token():
    from app.services import drive as drive_svc

    path = drive_svc.token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": "t", "refresh_token": "r"}), encoding="utf-8")


def _status(client, auth):
    resp = client.get(f"{API}/drive/status", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _put_config(client, auth, payload, expect=200):
    resp = client.put(f"{API}/drive/config", json=payload, headers=auth)
    assert resp.status_code == expect, resp.text
    return resp.json()


def _secret_file(name="client_secret_test.json", body=None) -> str:
    path = _data_dir() / name
    if body is None:
        body = json.dumps({"installed": {"client_id": "x", "client_secret": "y"}})
    path.write_text(body, encoding="utf-8")
    return str(path)


def _space(client, auth, name):
    resp = client.post(
        f"{API}/entities", json={"name": name, "kind": "space"}, headers=auth
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- status & config ----------------------------------------------------------


def test_drive_endpoints_require_auth(client):
    assert client.get(f"{API}/drive/status").status_code == 401
    assert client.post(f"{API}/drive/scan-now").status_code == 401


def test_status_unconfigured(client, auth):
    body = _status(client, auth)
    assert body["configured"] is False
    assert body["connected"] is False
    assert body["connect_pending"] is False
    assert body["email"] is None
    assert body["scans_folder"] is None
    assert body["poll_interval_min"] == 15  # migration seed
    assert body["backup_upload_enabled"] is False
    assert body["inbox_counts"] == {"new": 0, "attached": 0, "ignored": 0}


def test_connect_without_credentials_409(client, auth):
    resp = client.post(f"{API}/drive/connect", headers=auth)
    assert resp.status_code == 409


def test_config_credentials_path_missing_file_409(client, auth):
    resp = client.put(
        f"{API}/drive/config",
        json={"credentials_path": str(_data_dir() / "no-such-secret.json")},
        headers=auth,
    )
    assert resp.status_code == 409


def test_config_credentials_path_invalid_json_409(client, auth):
    path = _secret_file("bad_secret.json", body="not-json{")
    resp = client.put(f"{API}/drive/config", json={"credentials_path": path}, headers=auth)
    assert resp.status_code == 409


def test_config_credentials_path_no_installed_key_409(client, auth):
    path = _secret_file("web_secret.json", body=json.dumps({"web": {"client_id": "x"}}))
    resp = client.put(f"{API}/drive/config", json={"credentials_path": path}, headers=auth)
    assert resp.status_code == 409
    assert "installed" in resp.json()["detail"]


def test_config_poll_interval_bounds_422(client, auth):
    for bad in (4, 1441, 0, -3):
        resp = client.put(
            f"{API}/drive/config", json={"poll_interval_min": bad}, headers=auth
        )
        assert resp.status_code == 422, f"{bad}: {resp.text}"


def test_config_valid_credentials_configures(client, auth):
    path = _secret_file()
    body = _put_config(client, auth, {"credentials_path": path})
    assert body["configured"] is True
    assert body["connected"] is False  # no token yet


def test_config_credentials_path_null_clears(client, auth):
    """credentials_path: null clears the stored meta path -> configured false."""
    body = _put_config(client, auth, {"credentials_path": None})
    assert body["configured"] is False
    # Clearing again is a no-op, not an error.
    body = _put_config(client, auth, {"credentials_path": None})
    assert body["configured"] is False
    # Restore the configured state for the connect tests that follow.
    body = _put_config(client, auth, {"credentials_path": _secret_file()})
    assert body["configured"] is True


def test_config_updates_folder_interval_and_toggle(client, auth):
    body = _put_config(
        client,
        auth,
        {
            "scans_folder_id": "scans-1",
            "scans_folder_name": "Scans",
            "poll_interval_min": 30,
            "backup_upload_enabled": True,
        },
    )
    assert body["scans_folder"] == {"id": "scans-1", "name": "Scans"}
    assert body["poll_interval_min"] == 30
    assert body["backup_upload_enabled"] is True
    # Clearing the folder with explicit nulls works; reset toggle for later tests.
    body = _put_config(
        client,
        auth,
        {"scans_folder_id": None, "scans_folder_name": None, "backup_upload_enabled": False},
    )
    assert body["scans_folder"] is None
    assert body["backup_upload_enabled"] is False


# --- connect / disconnect -----------------------------------------------------


def test_connect_flow_pending_then_connected(client, auth, fake, monkeypatch):
    from app.services import drive as drive_svc

    def _fake_flow(secret, token_file):
        assert Path(secret).is_file()  # the configured client secret, read in place
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(
            json.dumps({"token": "t", "refresh_token": "r"}), encoding="utf-8"
        )

    monkeypatch.setattr(drive_svc, "run_installed_flow", _fake_flow)
    resp = client.post(f"{API}/drive/connect", headers=auth)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert "ON THE SERVER PC" in body["message"]
    assert "In production" in body["message"]  # consent-screen hint surfaced

    drive_svc._connect_thread.join(timeout=10)
    assert not drive_svc._connect_thread.is_alive()

    status = _status(client, auth)
    assert status["connected"] is True
    assert status["connect_pending"] is False
    assert status["email"] == "fake@example.com"  # via the fake client


def test_disconnect_deletes_token(client, auth):
    from app.models.drive import DriveAccount
    from app.services import drive as drive_svc

    # Seed per-account state that a DIFFERENT account must never inherit.
    db = _session()
    try:
        account = db.get(DriveAccount, 1)
        account.last_poll_at = "2026-07-18T00:00:00Z"
        account.backup_folder_id = "stale-backup-folder"
        db.commit()
    finally:
        db.close()

    assert drive_svc.token_path().is_file()
    resp = client.post(f"{API}/drive/disconnect", headers=auth)
    assert resp.status_code == 204
    assert not drive_svc.token_path().exists()
    status = _status(client, auth)
    assert status["connected"] is False
    assert status["email"] is None
    assert status["last_poll_at"] is None  # cutoff anchor cleared
    db = _session()
    try:
        assert db.get(DriveAccount, 1).backup_folder_id is None
    finally:
        db.close()


def test_stale_connect_completion_cannot_rewrite_token(client, auth, monkeypatch):
    """Disconnect while the consent window is still open: the flow's late
    completion must not resurrect token.json (generation race guard)."""
    import threading

    from app.services import drive as drive_svc

    release = threading.Event()

    def _slow_flow(secret, token_file):
        release.wait(timeout=10)  # consent tab left open…
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(json.dumps({"token": "stale"}), encoding="utf-8")

    monkeypatch.setattr(drive_svc, "run_installed_flow", _slow_flow)
    assert client.post(f"{API}/drive/connect", headers=auth).status_code == 202
    assert _status(client, auth)["connect_pending"] is True

    # …the user disconnects, THEN the consent completes.
    assert client.post(f"{API}/drive/disconnect", headers=auth).status_code == 204
    release.set()
    drive_svc._connect_thread.join(timeout=10)
    assert not drive_svc._connect_thread.is_alive()

    assert not drive_svc.token_path().exists()  # stale token was discarded
    status = _status(client, auth)
    assert status["connected"] is False
    assert status["connect_pending"] is False


def test_connected_via_fake_token_file(client, auth):
    # The remaining tests run in this connected state.
    _write_token()
    assert _status(client, auth)["connected"] is True


# --- browse -------------------------------------------------------------------


def test_browse_maps_folders_and_files(client, auth, fake):
    fake.add_folder("f-docs", "Documents")
    fake.add_file("doc-1", "scan-001.pdf", md5="aaa", size=999,
                  modified="2026-07-10T08:00:00Z")
    resp = client.get(f"{API}/drive/browse", headers=auth)  # folder_id defaults to root
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["folders"] == [{"id": "f-docs", "name": "Documents"}]
    assert body["files"] == [
        {
            "id": "doc-1",
            "name": "scan-001.pdf",
            "mime": "application/pdf",
            "modified_time": "2026-07-10T08:00:00Z",
            "size": 999,
        }
    ]

    sub = client.get(f"{API}/drive/browse", params={"folder_id": "f-docs"}, headers=auth)
    assert sub.json() == {"folders": [], "files": []}


def test_scan_now_without_folder_409(client, auth, fake):
    assert _status(client, auth)["scans_folder"] is None
    resp = client.post(f"{API}/drive/scan-now", headers=auth)
    assert resp.status_code == 409


# --- poller / inbox -----------------------------------------------------------


def test_scan_now_creates_rows(client, auth, fake):
    _put_config(client, auth, {"scans_folder_id": "scans-A", "scans_folder_name": "ScansA"})
    fake.add_folder("scans-A", "ScansA")
    fake.add_folder("sub", "Subfolder", parent="scans-A")  # folders are skipped
    fake.add_file("s1", "scan-a.pdf", parent="scans-A", md5="m1",
                  modified="2026-07-18T10:00:00Z")
    fake.add_file("s2", "scan-b.pdf", parent="scans-A", md5="m2",
                  modified="2026-07-18T11:00:00Z")

    resp = client.post(f"{API}/drive/scan-now", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"new": 2, "seen": 2}

    rows = client.get(f"{API}/drive/inbox", params={"status": "new"}, headers=auth).json()
    assert {r["drive_file_id"] for r in rows} == {"s1", "s2"}
    row = next(r for r in rows if r["drive_file_id"] == "s1")
    assert row["name"] == "scan-a.pdf"
    assert row["mime"] == "application/pdf"
    assert row["md5"] == "m1"
    assert row["size_bytes"] == 1234
    assert row["status"] == "new"
    assert row["attachment_id"] is None
    assert row["thumbnail_url"] is None
    assert _status(client, auth)["last_poll_at"] is not None


def test_rescan_refreshes_metadata_but_keeps_status(client, auth, fake):
    from app.services import drive as drive_svc
    from app.utils.dt import utcnow

    fake.add_folder("scans-A", "ScansA")
    fake.add_file("s1", "scan-a-renamed.pdf", parent="scans-A", md5="m1-v2",
                  modified=drive_svc._format_rfc3339(utcnow()))
    fake.add_file("s2", "scan-b.pdf", parent="scans-A", md5="m2",
                  modified=drive_svc._format_rfc3339(utcnow()))

    rows = client.get(f"{API}/drive/inbox", headers=auth).json()
    s2_id = next(r["id"] for r in rows if r["drive_file_id"] == "s2")
    ignored = client.post(f"{API}/drive/inbox/{s2_id}/ignore", headers=auth)
    assert ignored.status_code == 200
    assert ignored.json()["status"] == "ignored"

    resp = client.post(f"{API}/drive/scan-now", headers=auth)
    assert resp.json() == {"new": 0, "seen": 2}  # upsert, nothing new

    rows = {r["drive_file_id"]: r for r in client.get(f"{API}/drive/inbox", headers=auth).json()}
    assert rows["s1"]["name"] == "scan-a-renamed.pdf"  # metadata refreshed
    assert rows["s1"]["md5"] == "m1-v2"
    assert rows["s1"]["status"] == "new"
    assert rows["s2"]["status"] == "ignored"  # status survives the refresh


def test_scan_overlap_window(client, auth, fake):
    """The modifiedTime cutoff (last_poll_at - 5min) only optimizes away the
    metadata REFRESH of already-known rows — UNKNOWN ids are upserted no matter
    how old their modifiedTime is (the listing is always full)."""
    from app.models.drive import DriveAccount
    from app.services import drive as drive_svc
    from app.utils.dt import utcnow

    now = utcnow()
    db = _session()
    try:
        db.get(DriveAccount, 1).last_poll_at = drive_svc._format_rfc3339(now)
        db.commit()
    finally:
        db.close()

    fake.add_folder("scans-A", "ScansA")
    # KNOWN row with a 10-min-old modifiedTime (outside the overlap window):
    # its metadata refresh is skipped — the stale rename must NOT land.
    fake.add_file("s1", "s1-stale-rename.pdf", parent="scans-A", md5="m1-v3",
                  modified=drive_svc._format_rfc3339(now - timedelta(minutes=10)))
    # UNKNOWN id, 10 min old (e.g. an old file MOVED into the folder):
    # the cutoff must not hide it -> upserted regardless.
    fake.add_file("old", "too-old.pdf", parent="scans-A",
                  modified=drive_svc._format_rfc3339(now - timedelta(minutes=10)))
    # Unknown and 2 min old (inside the window) -> picked up as before.
    fake.add_file("recent", "recent.pdf", parent="scans-A",
                  modified=drive_svc._format_rfc3339(now - timedelta(minutes=2)))

    resp = client.post(f"{API}/drive/scan-now", headers=auth)
    assert resp.json() == {"new": 2, "seen": 3}
    rows = {r["drive_file_id"]: r for r in client.get(f"{API}/drive/inbox", headers=auth).json()}
    assert "old" in rows
    assert "recent" in rows
    assert rows["s1"]["name"] == "scan-a-renamed.pdf"  # stale-window refresh skipped


def test_scan_new_folder_full_of_old_files(client, auth, fake):
    """Pointing at a different folder nulls last_poll_at, so a library of
    years-old files is ingested in full on the first scan; afterwards a file
    moved in (old modifiedTime, unknown id) still appears with a live cutoff."""
    body = _put_config(
        client, auth, {"scans_folder_id": "scans-B", "scans_folder_name": "ScansB"}
    )
    assert body["last_poll_at"] is None  # folder change cleared the cutoff anchor

    fake.add_folder("scans-B", "ScansB")
    for i in range(3):
        fake.add_file(f"b{i}", f"archive-{i}.pdf", parent="scans-B",
                      modified=f"2019-01-0{i + 1}T00:00:00Z")
    resp = client.post(f"{API}/drive/scan-now", headers=auth)
    assert resp.json() == {"new": 3, "seen": 3}
    ids = {r["drive_file_id"] for r in client.get(f"{API}/drive/inbox", headers=auth).json()}
    assert {"b0", "b1", "b2"} <= ids

    # last_poll_at is now set — a file moved in with an ancient modifiedTime
    # (unknown id) must still be discovered on the next scan.
    fake.add_file("b-moved", "moved-2018.pdf", parent="scans-B",
                  modified="2018-06-01T00:00:00Z")
    resp = client.post(f"{API}/drive/scan-now", headers=auth)
    assert resp.json() == {"new": 1, "seen": 4}
    ids = {r["drive_file_id"] for r in client.get(f"{API}/drive/inbox", headers=auth).json()}
    assert "b-moved" in ids

    # Point back at scans-A for the tests that follow.
    _put_config(client, auth, {"scans_folder_id": "scans-A", "scans_folder_name": "ScansA"})


def test_inbox_attach_and_double_attach_409(client, auth, fake):
    entity = _space(client, auth, "DriveDocsRoom")
    rows = client.get(f"{API}/drive/inbox", params={"status": "new"}, headers=auth).json()
    row = next(r for r in rows if r["drive_file_id"] == "s1")

    resp = client.post(
        f"{API}/drive/inbox/{row['id']}/attach",
        json={"entity_id": entity["id"], "title": "Warranty scan"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["row"]["status"] == "attached"
    att = body["attachment"]
    assert body["row"]["attachment_id"] == att["id"]
    assert att["type"] == "drive_link"
    assert att["title"] == "Warranty scan"
    assert att["entity_id"] == entity["id"]
    assert att["drive_status"] == "ok"
    assert att["urls"]["open"] == "https://drive.google.com/file/d/s1/view"
    assert "original" not in att["urls"]

    # The drive_link attachment shows up in the entity's attachment list.
    listed = client.get(f"{API}/entities/{entity['id']}/attachments", headers=auth).json()
    assert [a["id"] for a in listed] == [att["id"]]

    # Attach again -> 409; ignore of an attached row -> 409.
    again = client.post(
        f"{API}/drive/inbox/{row['id']}/attach",
        json={"entity_id": entity["id"]},
        headers=auth,
    )
    assert again.status_code == 409
    assert client.post(f"{API}/drive/inbox/{row['id']}/ignore", headers=auth).status_code == 409

    counts = _status(client, auth)["inbox_counts"]
    assert counts["attached"] == 1
    assert counts["ignored"] == 1


def test_inbox_attach_missing_row_and_entity_404(client, auth, fake):
    assert (
        client.post(
            f"{API}/drive/inbox/99999/attach", json={"entity_id": 1}, headers=auth
        ).status_code
        == 404
    )
    rows = client.get(f"{API}/drive/inbox", params={"status": "new"}, headers=auth).json()
    assert rows, "expected at least one new row"
    resp = client.post(
        f"{API}/drive/inbox/{rows[0]['id']}/attach",
        json={"entity_id": 999999},
        headers=auth,
    )
    assert resp.status_code == 404


# --- attach any browsed file --------------------------------------------------


def test_attach_any_drive_file(client, auth, fake):
    entity = _space(client, auth, "DriveAnyRoom")
    fake.add_file("manual-1", "fridge-manual.pdf", md5="mm1", size=555,
                  modified="2026-07-01T09:00:00Z")

    resp = client.post(
        f"{API}/entities/{entity['id']}/attachments/drive",
        json={"file_id": "manual-1", "title": "Fridge manual"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    att = resp.json()
    assert att["type"] == "drive_link"
    assert att["mime"] == "application/pdf"
    assert att["byte_size"] == 555
    assert att["drive_status"] == "ok"
    assert att["urls"]["open"] == "https://drive.google.com/file/d/manual-1/view"

    # Same file on the SAME entity -> 409; a different entity is fine.
    dup = client.post(
        f"{API}/entities/{entity['id']}/attachments/drive",
        json={"file_id": "manual-1"},
        headers=auth,
    )
    assert dup.status_code == 409
    other = _space(client, auth, "DriveAnyRoom2")
    ok = client.post(
        f"{API}/entities/{other['id']}/attachments/drive",
        json={"file_id": "manual-1"},
        headers=auth,
    )
    assert ok.status_code == 201

    # Unknown Drive file -> 404.
    missing = client.post(
        f"{API}/entities/{entity['id']}/attachments/drive",
        json={"file_id": "nope"},
        headers=auth,
    )
    assert missing.status_code == 404


def test_attach_any_marks_matching_new_inbox_row(client, auth, fake):
    entity = _space(client, auth, "DriveAnyRoom3")
    rows = client.get(f"{API}/drive/inbox", params={"status": "new"}, headers=auth).json()
    row = next(r for r in rows if r["drive_file_id"] == "recent")
    fake.add_file("recent", "recent.pdf", md5="rm1")
    resp = client.post(
        f"{API}/entities/{entity['id']}/attachments/drive",
        json={"file_id": "recent"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    refreshed = client.get(f"{API}/drive/inbox", headers=auth).json()
    updated = next(r for r in refreshed if r["id"] == row["id"])
    assert updated["status"] == "attached"
    assert updated["attachment_id"] == resp.json()["id"]


# --- thumbnails ---------------------------------------------------------------


def test_thumbnail_ensure_caches_and_serves(client, auth, fake):
    fake.add_file("th-1", "scan-th.pdf", md5="thmd5",
                  thumbnail_link="https://thumb.example/th-1")
    fake.thumbnails["https://thumb.example/th-1"] = b"\xff\xd8\xe0fake-jpeg"

    resp = client.post(f"{API}/drive/thumbnail/th-1", headers=auth)
    assert resp.status_code == 200, resp.text
    url = resp.json()["url"]
    assert url == "/media/drive-cache/th-1/thmd5.jpg"  # per-id subdirectory
    assert (_data_dir() / "drive-cache" / "th-1" / "thmd5.jpg").is_file()

    # Served by /media (allowlist includes drive-cache/), no auth needed.
    served = client.get(url)
    assert served.status_code == 200
    assert served.content == b"\xff\xd8\xe0fake-jpeg"

    # Cache hit: NO further client calls.
    before = dict(fake.calls)
    again = client.post(f"{API}/drive/thumbnail/th-1", headers=auth)
    assert again.json()["url"] == url
    assert fake.calls["file_metadata"] == before["file_metadata"]
    assert fake.calls["download_thumbnail"] == before["download_thumbnail"]


def test_thumbnail_none_when_drive_offers_none(client, auth, fake):
    fake.add_file("th-2", "no-thumb.pdf", md5="x2", thumbnail_link=None)
    resp = client.post(f"{API}/drive/thumbnail/th-2", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["url"] is None
    assert not (_data_dir() / "drive-cache" / "th-2").exists()


def test_thumbnail_unknown_file_404(client, auth, fake):
    assert client.post(f"{API}/drive/thumbnail/ghost", headers=auth).status_code == 404


def test_thumbnail_path_like_file_id_409(client, auth, fake):
    """Path-like 'file ids' are rejected BEFORE any filesystem use. Single
    URL segment at the API level (the router can't even see encoded slashes
    consistently); the full separator zoo is pinned at the service level."""
    from app.services import drive as drive_svc
    from app.services.tree import RuleViolation

    assert client.post(f"{API}/drive/thumbnail/..%5C..%5Cx", headers=auth).status_code == 409
    assert client.post(f"{API}/drive/thumbnail/a..b", headers=auth).status_code == 409

    db = _session()
    try:
        for evil in ("..", "a/b", "a\\b", "..\\x", "a..b", ""):
            with pytest.raises(RuleViolation):
                drive_svc.ensure_thumbnail(db, evil)
    finally:
        db.close()


# --- reconciliation -----------------------------------------------------------


def test_reconcile_ok_missing_changed(client, auth, fake):
    entity = _space(client, auth, "ReconcileRoom")
    fake.add_file("rec-1", "rec.pdf", md5="r1", modified="2026-07-01T00:00:00Z")
    att = client.post(
        f"{API}/entities/{entity['id']}/attachments/drive",
        json={"file_id": "rec-1"},
        headers=auth,
    ).json()

    def _my_attachment():
        listed = client.get(f"{API}/entities/{entity['id']}/attachments", headers=auth).json()
        return next(a for a in listed if a["id"] == att["id"])

    # All present -> ok (other drive files attached by earlier tests still exist
    # in the fake only if added; keep them present).
    fake.add_file("s1", "scan-a-renamed.pdf", md5="m1-v2")
    fake.add_file("manual-1", "fridge-manual.pdf", md5="mm1")
    fake.add_file("recent", "recent.pdf", md5="rm1")
    resp = client.post(f"{API}/drive/reconcile", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["missing"] == 0
    assert body["changed"] == 0
    assert body["ok"] == 4  # rec-1, s1, manual-1, recent (distinct file ids)
    assert _my_attachment()["drive_status"] == "ok"

    # Trash it -> missing.
    fake.items["rec-1"]["trashed"] = True
    body = client.post(f"{API}/drive/reconcile", headers=auth).json()
    assert body["missing"] == 1
    assert _my_attachment()["drive_status"] == "missing"

    # Restore with new content -> changed + denormalized refresh.
    fake.add_file("rec-1", "rec-v2.pdf", md5="r2", modified="2026-07-19T00:00:00Z")
    body = client.post(f"{API}/drive/reconcile", headers=auth).json()
    assert body["changed"] == 1
    mine = _my_attachment()
    assert mine["drive_status"] == "changed"

    # Next cycle: the refreshed md5 matches -> back to ok.
    body = client.post(f"{API}/drive/reconcile", headers=auth).json()
    assert body["changed"] == 0
    assert _my_attachment()["drive_status"] == "ok"


# --- attach titles, entity links, thumb lifecycle (review fixes) --------------


def test_attach_any_defaults_title_to_drive_name(client, auth, fake):
    """No explicit title -> the Drive file name; AttachmentOut carries
    drive_file_id + drive_name (thumbnails / names on entity pages)."""
    entity = _space(client, auth, "DriveTitleRoom")
    fake.add_file("titled-1", "insurance-policy.pdf", md5="tp1", size=100)
    resp = client.post(
        f"{API}/entities/{entity['id']}/attachments/drive",
        json={"file_id": "titled-1"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    att = resp.json()
    assert att["title"] == "insurance-policy.pdf"
    assert att["drive_file_id"] == "titled-1"
    assert att["drive_name"] == "insurance-policy.pdf"
    # The listing carries the Drive fields too (thumbnails on entity pages).
    listed = client.get(f"{API}/entities/{entity['id']}/attachments", headers=auth).json()
    assert listed[0]["drive_file_id"] == "titled-1"
    assert listed[0]["drive_name"] == "insurance-policy.pdf"


def test_inbox_attach_defaults_title_and_links_entity(client, auth, fake):
    entity = _space(client, auth, "InboxTitleRoom")
    _put_config(client, auth, {"scans_folder_id": "scans-T", "scans_folder_name": "ScansT"})
    fake.add_folder("scans-T", "ScansT")
    fake.add_file("t-scan", "title-scan.pdf", parent="scans-T", md5="ts1")
    assert client.post(f"{API}/drive/scan-now", headers=auth).status_code == 200

    rows = client.get(f"{API}/drive/inbox", params={"status": "new"}, headers=auth).json()
    row = next(r for r in rows if r["drive_file_id"] == "t-scan")
    resp = client.post(
        f"{API}/drive/inbox/{row['id']}/attach",
        json={"entity_id": entity["id"]},  # no title
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attachment"]["title"] == "title-scan.pdf"  # defaulted to the name
    assert body["attachment"]["drive_file_id"] == "t-scan"
    assert body["row"]["entity_id"] == entity["id"]
    assert body["row"]["entity_name"] == "InboxTitleRoom"

    # The attached tab carries the entity link and a timezone-AWARE timestamp.
    attached = client.get(
        f"{API}/drive/inbox", params={"status": "attached"}, headers=auth
    ).json()
    mine = next(r for r in attached if r["drive_file_id"] == "t-scan")
    assert mine["entity_id"] == entity["id"]
    assert mine["entity_name"] == "InboxTitleRoom"
    assert mine["discovered_at"].endswith("Z") or "+00:00" in mine["discovered_at"]


def test_thumbnail_stale_md5_refetches(client, auth, fake):
    """A cache hit whose md5 no longer matches the tracked one refetches and
    drops the old file."""
    entity = _space(client, auth, "ThumbStaleRoom")
    fake.add_file("st-1", "stale.pdf", md5="v1",
                  thumbnail_link="https://thumb.example/st-1")
    fake.thumbnails["https://thumb.example/st-1"] = b"\xff\xd8v1"
    client.post(
        f"{API}/entities/{entity['id']}/attachments/drive",
        json={"file_id": "st-1"},
        headers=auth,
    )
    url = client.post(f"{API}/drive/thumbnail/st-1", headers=auth).json()["url"]
    assert url == "/media/drive-cache/st-1/v1.jpg"

    # Content changes on Drive; only the TRACKED md5 gets refreshed (as a scan
    # or reconcile would do) while the cached file still holds v1.
    fake.add_file("st-1", "stale.pdf", md5="v2",
                  thumbnail_link="https://thumb.example/st-1")
    fake.thumbnails["https://thumb.example/st-1"] = b"\xff\xd8v2"
    from sqlalchemy import select

    from app.models.attachment import Attachment

    db = _session()
    try:
        att_row = db.scalar(select(Attachment).where(Attachment.drive_file_id == "st-1"))
        att_row.drive_md5 = "v2"
        db.commit()
    finally:
        db.close()

    before = dict(fake.calls)
    resp = client.post(f"{API}/drive/thumbnail/st-1", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "/media/drive-cache/st-1/v2.jpg"
    assert fake.calls["download_thumbnail"] == before["download_thumbnail"] + 1
    assert not (_data_dir() / "drive-cache" / "st-1" / "v1.jpg").exists()
    assert (_data_dir() / "drive-cache" / "st-1" / "v2.jpg").is_file()


def test_deleting_drive_attachment_deletes_cached_thumbs(client, auth, fake):
    entity = _space(client, auth, "ThumbCleanupRoom")
    fake.add_file("tc-1", "cleanup.pdf", md5="tcmd5",
                  thumbnail_link="https://thumb.example/tc-1")
    fake.thumbnails["https://thumb.example/tc-1"] = b"\xff\xd8tc"
    att = client.post(
        f"{API}/entities/{entity['id']}/attachments/drive",
        json={"file_id": "tc-1"},
        headers=auth,
    ).json()
    url = client.post(f"{API}/drive/thumbnail/tc-1", headers=auth).json()["url"]
    assert url == "/media/drive-cache/tc-1/tcmd5.jpg"
    cached = _data_dir() / "drive-cache" / "tc-1" / "tcmd5.jpg"
    assert cached.is_file()

    resp = client.delete(f"{API}/attachments/{att['id']}", headers=auth)
    assert resp.status_code == 204
    assert not cached.exists()


# --- backup push --------------------------------------------------------------


def test_backup_now_uploads_and_caches_folder_id(client, auth, fake):
    from app.models.drive import DriveAccount

    resp = client.post(f"{API}/drive/backup-now", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["file"].startswith("db-") and body["file"].endswith(".db")
    assert body["drive_file_id"] == "up1"
    assert fake.calls["ensure_folder"] == 1
    assert len(fake.upload_log) == 1
    assert fake.upload_log[0]["name"] == body["file"]
    assert fake.upload_log[0]["parent"] == "folder-Archiviator Backups"
    # The uploaded local path is the fresh snapshot in backups/.
    assert Path(fake.upload_log[0]["local_path"]).parent.name == "backups"
    assert Path(fake.upload_log[0]["local_path"]).is_file()

    db = _session()
    try:
        account = db.get(DriveAccount, 1)
        assert account.backup_folder_id == "folder-Archiviator Backups"
        assert account.last_backup_upload_at is not None
    finally:
        db.close()

    # Cached folder id: second upload never re-ensures the folder.
    resp = client.post(f"{API}/drive/backup-now", headers=auth)
    assert resp.status_code == 200
    assert fake.calls["ensure_folder"] == 1
    assert len(fake.upload_log) == 2
    assert _status(client, auth)["last_backup_upload_at"] is not None


def test_backup_upload_reensures_when_cached_folder_gone(client, auth, fake):
    """The cached backup_folder_id is only trusted until an upload proves the
    folder gone: then drop the cache, re-ensure once and retry once."""
    from app.models.drive import DriveAccount

    db = _session()
    try:
        db.get(DriveAccount, 1).backup_folder_id = "gone-folder"  # deleted on Drive
        db.commit()
    finally:
        db.close()

    resp = client.post(f"{API}/drive/backup-now", headers=auth)
    assert resp.status_code == 200, resp.text
    assert fake.calls["upload_file"] == 2  # failed attempt + successful retry
    assert fake.calls["ensure_folder"] == 1  # re-ensured exactly once
    assert len(fake.upload_log) == 1
    assert fake.upload_log[0]["parent"] == "folder-Archiviator Backups"
    db = _session()
    try:
        # The fresh folder id is re-cached for the next push.
        assert db.get(DriveAccount, 1).backup_folder_id == "folder-Archiviator Backups"
    finally:
        db.close()


def test_backup_prune_keeps_newest_seven(client, auth, fake):
    from app.models.drive import DriveAccount

    db = _session()
    try:
        db.get(DriveAccount, 1).backup_folder_id = "bfold"
        db.commit()
    finally:
        db.close()

    fake.add_folder("bfold", "Archiviator Backups")
    for i in range(8):
        fake.add_file(f"oldbk-{i}", f"db-2020010{i}-000000.db", parent="bfold",
                      mime="application/octet-stream")
    fake.add_file("notdb", "notes.txt", parent="bfold", mime="text/plain")  # never pruned

    resp = client.post(f"{API}/drive/backup-now", headers=auth)
    assert resp.status_code == 200, resp.text
    # 8 old + 1 fresh = 9 snapshots -> keep newest 7, delete the 2 oldest.
    assert fake.delete_log == ["oldbk-0", "oldbk-1"]
    assert "notdb" in fake.items  # non-snapshot files untouched
    remaining = [
        i["name"] for i in fake.items.values()
        if i["parent"] == "bfold" and i["name"].startswith("db-")
    ]
    assert len(remaining) == 7


def test_nightly_job_runs_drive_push_after_local_backup(client, auth, fake):
    from app.models.drive import DriveAccount
    from app.services.scheduler import nightly_backup

    _put_config(client, auth, {"backup_upload_enabled": True})
    db = _session()
    try:
        db.get(DriveAccount, 1).backup_folder_id = "bfold"
        db.commit()
    finally:
        db.close()
    fake.add_folder("bfold", "Archiviator Backups")

    result = nightly_backup()
    assert (_data_dir() / "backups" / result["file"]).exists()  # local backup first
    assert len(fake.upload_log) == 1
    assert fake.upload_log[0]["name"] == result["file"]  # then the push
    _put_config(client, auth, {"backup_upload_enabled": False})


def test_nightly_job_skips_drive_when_disconnected(client, auth, fake):
    from app.services import drive as drive_svc
    from app.services.scheduler import nightly_backup

    drive_svc.token_path().unlink(missing_ok=True)
    result = nightly_backup()  # local backup must still succeed
    assert (_data_dir() / "backups" / result["file"]).exists()
    assert fake.upload_log == []
    _write_token()  # restore the connected state for any later test


# --- export.zip exclusions ----------------------------------------------------


def test_export_zip_excludes_gdrive_and_drive_cache(client, auth):
    from app.services import drive as drive_svc

    assert drive_svc.token_path().is_file()  # the OAuth token exists on disk
    cache = _data_dir() / "drive-cache"
    cache.mkdir(exist_ok=True)
    (cache / "zip-check.jpg").write_bytes(b"\xff\xd8x")

    resp = client.get(f"{API}/admin/export.zip", headers=auth)
    assert resp.status_code == 200, resp.text
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert not any(n.startswith("gdrive/") for n in names)
    assert not any(n.startswith("drive-cache/") for n in names)


# --- scheduler wiring ---------------------------------------------------------


def test_build_scheduler_reads_poll_interval_from_db(client, auth):
    from app.config import get_settings
    from app.services.scheduler import DRIVE_POLL_JOB_ID, build_scheduler

    _put_config(client, auth, {"poll_interval_min": 44})
    scheduler = build_scheduler(get_settings())
    job = next(j for j in scheduler.get_jobs() if j.id == DRIVE_POLL_JOB_ID)
    assert job.trigger.interval == timedelta(minutes=44)


def test_config_put_reschedules_live_scheduler(client, auth):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app.services.scheduler import DRIVE_POLL_JOB_ID

    assert client.app.state.scheduler is None  # disabled scheduler is tolerated…
    _put_config(client, auth, {"poll_interval_min": 25})  # …and the PUT still works

    scheduler = AsyncIOScheduler()
    client.app.state.scheduler = scheduler
    try:
        _put_config(client, auth, {"poll_interval_min": 60})
        job = next(j for j in scheduler.get_jobs() if j.id == DRIVE_POLL_JOB_ID)
        assert job.trigger.interval == timedelta(minutes=60)
        # Rescheduling again replaces, not duplicates.
        _put_config(client, auth, {"poll_interval_min": 90})
        jobs = [j for j in scheduler.get_jobs() if j.id == DRIVE_POLL_JOB_ID]
        assert len(jobs) == 1
        assert jobs[0].trigger.interval == timedelta(minutes=90)
    finally:
        client.app.state.scheduler = None
