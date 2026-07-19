"""M3 attachment tests: upload pipeline, dedup/refcounting, cover, /media serving.

All image fixtures are generated in code with Pillow (plus pillow_heif for the
HEIC case) — no binary fixtures on disk.
"""

import io
from pathlib import Path

import pillow_heif
import pytest
from PIL import Image

API = "/api/v1"

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


@pytest.fixture(scope="module")
def auth(client, test_user):
    """One login for the whole module (same pattern as test_tree)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _space(client, auth, name):
    resp = client.post(
        f"{API}/entities", json={"name": name, "kind": "space"}, headers=auth
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload(client, auth, entity_id, data, filename="upload.bin", title=None):
    form = {"title": title} if title is not None else None
    return client.post(
        f"{API}/entities/{entity_id}/attachments",
        files={"file": (filename, data, "application/octet-stream")},
        data=form,
        headers=auth,
    )


def _jpeg(size=(800, 600), color=(120, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _fetch_image(client, url):
    resp = client.get(url)  # deliberately no auth headers: /media is public
    assert resp.status_code == 200, url
    return Image.open(io.BytesIO(resp.content))


def _data_dir() -> Path:
    from app.config import get_settings

    return get_settings().data_dir


def _hash_from_url(url: str) -> str:
    return Path(url).stem.split("_")[0]


# --- auth & shape -------------------------------------------------------------


def test_attachment_endpoints_require_auth(client, auth):
    e = _space(client, auth, "AttAuth")
    assert client.get(f"{API}/entities/{e['id']}/attachments").status_code == 401
    assert client.post(f"{API}/entities/{e['id']}/attachments").status_code == 401


def test_upload_jpeg_shape_and_title(client, auth):
    e = _space(client, auth, "AttShape")
    resp = _upload(client, auth, e["id"], _jpeg(), "photo.jpg", title="My photo")
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert set(a.keys()) == {
        "id", "entity_id", "type", "title", "sort_order", "mime", "byte_size",
        "width", "height", "is_cover", "urls", "created_at",
        "drive_status", "drive_file_id", "drive_name",  # M9 drive_link fields
    }
    assert a["entity_id"] == e["id"]
    assert a["drive_status"] is None  # stored photo, not a drive_link
    assert a["drive_file_id"] is None
    assert a["drive_name"] is None
    assert a["type"] == "photo"
    assert a["title"] == "My photo"
    assert a["sort_order"] == 0
    assert a["mime"] == "image/jpeg"
    assert a["byte_size"] > 0
    assert (a["width"], a["height"]) == (800, 600)
    assert a["is_cover"] is False
    assert a["urls"]["original"].startswith("/media/attachments/")
    assert a["urls"]["display"].endswith("_1600.jpg")
    assert a["urls"]["thumb"].endswith("_320.jpg")


def test_upload_to_unknown_entity_404(client, auth):
    assert _upload(client, auth, 999999, _jpeg()).status_code == 404


# --- pipeline -----------------------------------------------------------------


def test_exif_orientation_transposed_and_stripped(client, auth):
    e = _space(client, auth, "AttExif")
    img = Image.new("RGB", (600, 400), (0, 80, 200))
    exif = Image.Exif()
    exif[274] = 6  # Orientation: rotate — width/height must swap
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, exif=exif.tobytes())

    resp = _upload(client, auth, e["id"], buf.getvalue(), "rotated.jpg")
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert (a["width"], a["height"]) == (400, 600)

    served = _fetch_image(client, a["urls"]["original"])
    assert served.size == (400, 600)
    assert 274 not in served.getexif()  # EXIF stripped, orientation not re-applied


def test_heic_converted_to_jpeg(client, auth):
    e = _space(client, auth, "AttHeic")
    buf = io.BytesIO()
    pillow_heif.from_pillow(Image.new("RGB", (500, 300), (10, 200, 10))).save(buf)
    resp = _upload(client, auth, e["id"], buf.getvalue(), "shot.heic")
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert a["type"] == "photo"
    assert a["mime"] == "image/jpeg"
    assert (a["width"], a["height"]) == (500, 300)
    assert a["urls"]["original"].endswith(".jpg")


def test_png_with_alpha_flattened_to_white_jpeg(client, auth):
    e = _space(client, auth, "AttAlpha")
    buf = io.BytesIO()
    Image.new("RGBA", (100, 80), (255, 0, 0, 0)).save(buf, "PNG")  # fully transparent
    resp = _upload(client, auth, e["id"], buf.getvalue(), "ghost.png")
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert a["mime"] == "image/jpeg"
    assert a["urls"]["original"].endswith(".jpg")

    served = _fetch_image(client, a["urls"]["original"])
    assert served.mode == "RGB"
    r, g, b = served.getpixel((50, 40))
    assert min(r, g, b) > 245  # transparent red flattened onto white


def test_opaque_small_png_stays_png(client, auth):
    e = _space(client, auth, "AttPng")
    buf = io.BytesIO()
    Image.new("RGB", (120, 90), (5, 5, 200)).save(buf, "PNG")
    resp = _upload(client, auth, e["id"], buf.getvalue(), "solid.png")
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert a["mime"] == "image/png"
    assert a["urls"]["original"].endswith(".png")
    # Derivatives are still JPEG.
    assert _fetch_image(client, a["urls"]["thumb"]).size == (120, 90)


def test_oversized_capped_at_3000_with_derivatives(client, auth):
    e = _space(client, auth, "AttBig")
    resp = _upload(client, auth, e["id"], _jpeg((4000, 2000), (40, 40, 40)), "big.jpg")
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert (a["width"], a["height"]) == (3000, 1500)
    assert _fetch_image(client, a["urls"]["original"]).size == (3000, 1500)
    assert _fetch_image(client, a["urls"]["display"]).size == (1600, 800)
    assert _fetch_image(client, a["urls"]["thumb"]).size == (320, 160)

    content_hash = _hash_from_url(a["urls"]["original"])
    root = _data_dir()
    assert (root / "attachments" / content_hash[:2] / f"{content_hash}.jpg").is_file()
    assert (root / "derived" / f"{content_hash}_1600.jpg").is_file()
    assert (root / "derived" / f"{content_hash}_320.jpg").is_file()


def test_pdf_stored_verbatim_no_derivatives(client, auth):
    e = _space(client, auth, "AttPdf")
    resp = _upload(client, auth, e["id"], PDF_BYTES, "manual.pdf")
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert a["type"] == "document"
    assert a["mime"] == "application/pdf"
    assert a["byte_size"] == len(PDF_BYTES)
    assert a["width"] is None and a["height"] is None
    assert set(a["urls"].keys()) == {"original"}
    assert a["urls"]["original"].endswith(".pdf")

    served = client.get(a["urls"]["original"])
    assert served.status_code == 200
    assert served.content == PDF_BYTES


def test_text_file_415(client, auth):
    e = _space(client, auth, "AttText")
    resp = _upload(client, auth, e["id"], b"hello world, not an image", "note.txt")
    assert resp.status_code == 415


def test_oversized_upload_413(client, auth, monkeypatch):
    import app.services.media as media

    monkeypatch.setattr(media, "MAX_UPLOAD", 100)
    e = _space(client, auth, "AttHuge")
    resp = _upload(client, auth, e["id"], _jpeg(), "huge.jpg")
    assert resp.status_code == 413


# --- dedup & refcounted delete ------------------------------------------------


def test_dedup_two_rows_one_file_refcounted_delete(client, auth):
    e = _space(client, auth, "AttDedup")
    data = _jpeg((333, 222), (7, 77, 177))  # unique content -> unique hash
    a1 = _upload(client, auth, e["id"], data, "one.jpg").json()
    a2 = _upload(client, auth, e["id"], data, "two.jpg").json()
    assert a1["id"] != a2["id"]
    assert a1["urls"] == a2["urls"]  # same content-addressed files
    assert (a1["byte_size"], a1["width"], a1["height"]) == (
        a2["byte_size"], a2["width"], a2["height"],
    )

    content_hash = _hash_from_url(a1["urls"]["original"])
    root = _data_dir()
    original = root / "attachments" / content_hash[:2] / f"{content_hash}.jpg"
    derived = [root / "derived" / f"{content_hash}_{s}.jpg" for s in (1600, 320)]
    assert original.is_file()
    # Exactly ONE stored file for this hash despite two rows.
    assert len(list(original.parent.glob(f"{content_hash}.*"))) == 1

    # Delete the first row: the second still references the files.
    assert client.delete(f"{API}/attachments/{a1['id']}", headers=auth).status_code == 204
    assert original.is_file()
    assert all(p.is_file() for p in derived)

    # Delete the last row: original and derivatives are unlinked.
    assert client.delete(f"{API}/attachments/{a2['id']}", headers=auth).status_code == 204
    assert not original.exists()
    assert all(not p.exists() for p in derived)


def test_delete_unknown_attachment_404(client, auth):
    assert client.delete(f"{API}/attachments/999999", headers=auth).status_code == 404


# --- metadata & listing order -------------------------------------------------


def test_patch_title_and_sort_order(client, auth):
    e = _space(client, auth, "AttPatch")
    a = _upload(client, auth, e["id"], _jpeg((50, 50), (1, 2, 3)), "p.jpg").json()

    resp = client.patch(f"{API}/attachments/{a['id']}", json={"title": "Front"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Front"

    # sort_order-only patch leaves title untouched.
    resp = client.patch(f"{API}/attachments/{a['id']}", json={"sort_order": 3}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["sort_order"] == 3
    assert resp.json()["title"] == "Front"

    # Explicit null clears the title.
    resp = client.patch(f"{API}/attachments/{a['id']}", json={"title": None}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["title"] is None

    assert client.patch(
        f"{API}/attachments/999999", json={"title": "X"}, headers=auth
    ).status_code == 404


def test_listing_ordered_by_sort_order_then_created(client, auth):
    e = _space(client, auth, "AttOrder")
    a1 = _upload(client, auth, e["id"], _jpeg((60, 60), (9, 9, 9)), "a.jpg").json()
    a2 = _upload(client, auth, e["id"], _jpeg((61, 61), (9, 9, 9)), "b.jpg").json()
    a3 = _upload(client, auth, e["id"], _jpeg((62, 62), (9, 9, 9)), "c.jpg").json()

    # All sort_order 0 -> upload (created_at) order.
    ids = [x["id"] for x in client.get(f"{API}/entities/{e['id']}/attachments", headers=auth).json()]
    assert ids == [a1["id"], a2["id"], a3["id"]]

    client.patch(f"{API}/attachments/{a1['id']}", json={"sort_order": 2}, headers=auth)
    client.patch(f"{API}/attachments/{a2['id']}", json={"sort_order": 1}, headers=auth)
    ids = [x["id"] for x in client.get(f"{API}/entities/{e['id']}/attachments", headers=auth).json()]
    assert ids == [a3["id"], a2["id"], a1["id"]]

    assert client.get(f"{API}/entities/999999/attachments", headers=auth).status_code == 404


# --- cover --------------------------------------------------------------------


def test_cover_set_appears_in_entity_out(client, auth):
    e = _space(client, auth, "CoverSet")
    photo = _upload(client, auth, e["id"], _jpeg((70, 70), (100, 0, 100)), "p.jpg").json()

    resp = client.put(
        f"{API}/entities/{e['id']}/cover", json={"attachment_id": photo["id"]}, headers=auth
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cover_attachment_id"] == photo["id"]
    assert body["thumb_url"] == photo["urls"]["thumb"]

    fetched = client.get(f"{API}/entities/{e['id']}", headers=auth).json()
    assert fetched["cover_attachment_id"] == photo["id"]
    assert fetched["thumb_url"] == photo["urls"]["thumb"]

    listed = client.get(f"{API}/entities/{e['id']}/attachments", headers=auth).json()
    assert [a["is_cover"] for a in listed] == [True]

    # Clear with null.
    resp = client.put(f"{API}/entities/{e['id']}/cover", json={"attachment_id": None}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["cover_attachment_id"] is None
    assert resp.json()["thumb_url"] is None


def test_cover_409_for_non_photo_foreign_and_unknown(client, auth):
    e = _space(client, auth, "CoverRules")
    other = _space(client, auth, "CoverOther")
    pdf = _upload(client, auth, e["id"], PDF_BYTES, "doc.pdf").json()
    foreign = _upload(client, auth, other["id"], _jpeg((71, 71), (0, 100, 100)), "f.jpg").json()

    for bad_id in (pdf["id"], foreign["id"], 999999):
        resp = client.put(
            f"{API}/entities/{e['id']}/cover", json={"attachment_id": bad_id}, headers=auth
        )
        assert resp.status_code == 409, f"attachment_id={bad_id}: {resp.text}"

    assert client.put(
        f"{API}/entities/999999/cover", json={"attachment_id": None}, headers=auth
    ).status_code == 404


def test_cover_clears_when_attachment_deleted(client, auth):
    e = _space(client, auth, "CoverDel")
    photo = _upload(client, auth, e["id"], _jpeg((72, 72), (50, 60, 70)), "p.jpg").json()
    assert client.put(
        f"{API}/entities/{e['id']}/cover", json={"attachment_id": photo["id"]}, headers=auth
    ).status_code == 200

    assert client.delete(f"{API}/attachments/{photo['id']}", headers=auth).status_code == 204
    fetched = client.get(f"{API}/entities/{e['id']}", headers=auth).json()
    assert fetched["cover_attachment_id"] is None
    assert fetched["thumb_url"] is None


# --- /media serving -----------------------------------------------------------


def test_media_serving_immutable_cache_and_no_auth(client, auth):
    e = _space(client, auth, "MediaServe")
    a = _upload(client, auth, e["id"], _jpeg((73, 73), (20, 20, 20)), "m.jpg").json()
    resp = client.get(a["urls"]["original"])  # no Authorization header
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert resp.headers["content-type"] == "image/jpeg"


def test_media_rejects_paths_outside_served_subtrees(client, auth):
    # secret.key really exists in data_dir (auth fixture logged in) — it must
    # never be reachable.
    assert (_data_dir() / "secret.key").is_file()
    assert client.get("/media/secret.key").status_code == 404
    assert client.get("/media/archiviator.db").status_code == 404
    # Encoded traversal (raw '..' would be normalized away by the HTTP client).
    assert client.get("/media/attachments/%2e%2e/secret.key").status_code == 404
    assert client.get("/media/derived/%2e%2e/%2e%2e/secret.key").status_code == 404


def test_media_unknown_path_404_not_spa_fallback(client):
    for path in ("/media/attachments/zz/nope.jpg", "/media/derived/nope_320.jpg", "/media/"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert "text/html" not in resp.headers.get("content-type", ""), path


# --- M3 hardening (adversarial-review regressions) ----------------------------


def test_patch_sort_order_null_is_422(client, auth):
    e = _space(client, auth, "NullSort")
    att = _upload(client, auth, e["id"], _jpeg()).json()
    resp = client.patch(
        f"{API}/attachments/{att['id']}", json={"sort_order": None}, headers=auth
    )
    assert resp.status_code == 422


def test_entity_delete_cleans_up_unreferenced_files(client, auth):
    e = _space(client, auth, "DelWithFiles")
    att = _upload(client, auth, e["id"], _jpeg(color=(1, 2, 3))).json()
    original = _data_dir() / att["urls"]["original"].removeprefix("/media/")
    thumb = _data_dir() / att["urls"]["thumb"].removeprefix("/media/")
    assert original.exists() and thumb.exists()

    assert client.delete(f"{API}/entities/{e['id']}", headers=auth).status_code == 204
    assert not original.exists(), "entity delete must run refcounted file cleanup"
    assert not thumb.exists()


def test_entity_delete_keeps_files_shared_with_other_entity(client, auth):
    data = _jpeg(color=(4, 5, 6))
    a = _space(client, auth, "ShareA")
    b = _space(client, auth, "ShareB")
    att_a = _upload(client, auth, a["id"], data).json()
    att_b = _upload(client, auth, b["id"], data).json()
    assert _hash_from_url(att_a["urls"]["original"]) == _hash_from_url(
        att_b["urls"]["original"]
    )
    original = _data_dir() / att_a["urls"]["original"].removeprefix("/media/")

    assert client.delete(f"{API}/entities/{a['id']}", headers=auth).status_code == 204
    assert original.exists(), "file still referenced by the other entity's attachment"
    assert client.delete(f"{API}/entities/{b['id']}", headers=auth).status_code == 204
    assert not original.exists()


def test_decompression_bomb_is_415_not_500(client, auth, monkeypatch):
    from PIL import Image as PILImage

    e = _space(client, auth, "Bomb")
    # A normal image over a tiny pixel cap raises DecompressionBombError exactly
    # like a 400-megapixel JPEG would over the real cap.
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 10_000)
    resp = _upload(client, auth, e["id"], _jpeg(size=(400, 300)))
    assert resp.status_code == 415


def test_head_media_returns_headers(client, auth):
    e = _space(client, auth, "HeadMedia")
    att = _upload(client, auth, e["id"], _jpeg(color=(7, 8, 9))).json()
    resp = client.head(att["urls"]["original"])
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert not resp.content


def test_pdf_with_leading_junk_is_document(client, auth):
    e = _space(client, auth, "BomPdf")
    resp = _upload(client, auth, e["id"], b"\xef\xbb\xbfjunk" + PDF_BYTES, "scan.pdf")
    assert resp.status_code == 201, resp.text
    assert resp.json()["type"] == "document"


def test_listing_endpoints_carry_cover_thumb(client, auth):
    root = _space(client, auth, "ThumbListRoot")
    resp = client.post(
        f"{API}/entities",
        json={"name": "ThumbChild", "kind": "item", "parent_id": root["id"]},
        headers=auth,
    )
    child = resp.json()
    att = _upload(client, auth, child["id"], _jpeg(color=(10, 11, 12))).json()
    put = client.put(
        f"{API}/entities/{child['id']}/cover",
        json={"attachment_id": att["id"]},
        headers=auth,
    )
    assert put.status_code == 200

    tree_row = next(
        e
        for e in client.get(f"{API}/entities/tree", headers=auth).json()
        if e["id"] == child["id"]
    )
    assert tree_row["cover_attachment_id"] == att["id"]
    assert tree_row["thumb_url"] == att["urls"]["thumb"]

    child_row = next(
        e
        for e in client.get(f"{API}/entities/{root['id']}/children", headers=auth).json()
        if e["id"] == child["id"]
    )
    assert child_row["thumb_url"] == att["urls"]["thumb"]


def test_stray_tmp_file_does_not_break_derivative_regeneration(client, auth):
    e = _space(client, auth, "TmpStray")
    att = _upload(client, auth, e["id"], _jpeg(color=(13, 14, 15))).json()
    content_hash = _hash_from_url(att["urls"]["original"])
    original = _data_dir() / att["urls"]["original"].removeprefix("/media/")
    stray = original.with_suffix(original.suffix + ".tmp")
    stray.write_bytes(b"partial garbage")
    for key in ("display", "thumb"):
        (_data_dir() / att["urls"][key].removeprefix("/media/")).unlink()

    from app.services.media import ensure_derivatives

    assert ensure_derivatives(content_hash) is True
    assert (_data_dir() / att["urls"]["thumb"].removeprefix("/media/")).exists()
    stray.unlink()
