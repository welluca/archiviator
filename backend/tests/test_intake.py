"""M7 intake tests: one-shot capture, device tokens (create/list/revoke/expiry +
the capture scope wall), drafts listing and batch promote with per-entity
SAVEPOINT isolation.

The 'inbox empties' test runs LAST in this module on purpose: it promotes every
draft left behind by the earlier tests and asserts /intake/drafts is empty."""

import io
import re

import pytest
from PIL import Image

API = "/api/v1"

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"

NAME_RE = re.compile(r"^Capture \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


@pytest.fixture(scope="module")
def auth(client, test_user):
    """One login for the whole module (same pattern as test_tree)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _jpeg(color, size=(200, 150)):
    # Callers pass a UNIQUE color so content hashes never collide across tests.
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _capture(client, headers, data, name=None, note=None, filename="shot.jpg"):
    form = {}
    if name is not None:
        form["name"] = name
    if note is not None:
        form["note"] = note
    return client.post(
        f"{API}/intake/capture",
        files={"file": (filename, data, "image/jpeg")},
        data=form or None,
        headers=headers,
    )


def _make(client, auth, name, kind, parent_id=None):
    resp = client.post(
        f"{API}/entities",
        json={"name": name, "kind": kind, "parent_id": parent_id},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _inbox(client, auth):
    rows = client.get(f"{API}/entities/tree", headers=auth).json()
    return next(e for e in rows if e["protected"])


def _get(client, auth, entity_id):
    resp = client.get(f"{API}/entities/{entity_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _drafts(client, auth):
    resp = client.get(f"{API}/intake/drafts", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _promote(client, auth, payload):
    return client.post(f"{API}/intake/promote", json=payload, headers=auth)


def _mint(client, auth, label):
    resp = client.post(f"{API}/auth/device-tokens", json={"label": label}, headers=auth)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- capture ------------------------------------------------------------------


def test_capture_happy_path(client, auth):
    inbox = _inbox(client, auth)
    resp = _capture(client, auth, _jpeg((1, 2, 3)), note="from the phone")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    entity, attachment = body["entity"], body["attachment"]

    assert entity["kind"] == "item"
    assert entity["parent_id"] == inbox["id"]
    assert entity["draft"] is True
    assert entity["notes"] == "from the phone"
    assert NAME_RE.match(entity["name"]), entity["name"]
    assert entity["cover_attachment_id"] == attachment["id"]
    assert entity["thumb_url"] == attachment["urls"]["thumb"]

    assert attachment["entity_id"] == entity["id"]
    assert attachment["type"] == "photo"
    assert attachment["is_cover"] is True

    # It shows up in the drafts pile AND in the normal children listing.
    assert entity["id"] in [d["id"] for d in _drafts(client, auth)]
    children = client.get(f"{API}/entities/{inbox['id']}/children", headers=auth).json()
    row = next(c for c in children if c["id"] == entity["id"])
    assert row["draft"] is True


def test_capture_custom_name_kept(client, auth):
    resp = _capture(client, auth, _jpeg((2, 3, 4)), name="Garage find")
    assert resp.status_code == 201, resp.text
    assert resp.json()["entity"]["name"] == "Garage find"


def test_capture_blank_name_falls_back_to_default(client, auth):
    resp = _capture(client, auth, _jpeg((3, 4, 5)), name="   ")
    assert resp.status_code == 201, resp.text
    assert NAME_RE.match(resp.json()["entity"]["name"])


def test_capture_requires_auth(client):
    resp = _capture(client, None, _jpeg((4, 5, 6)))
    assert resp.status_code == 401


def test_capture_text_file_415_and_no_draft_left(client, auth):
    before = len(_drafts(client, auth))
    resp = _capture(client, auth, b"hello, not an image", filename="note.txt")
    assert resp.status_code == 415
    assert len(_drafts(client, auth)) == before


def test_capture_pdf_415_photos_only(client, auth):
    resp = _capture(client, auth, PDF_BYTES, filename="doc.pdf")
    assert resp.status_code == 415


def test_capture_oversized_413(client, auth, monkeypatch):
    import app.services.media as media

    monkeypatch.setattr(media, "MAX_UPLOAD", 100)
    before = len(_drafts(client, auth))
    resp = _capture(client, auth, _jpeg((5, 6, 7)))
    assert resp.status_code == 413
    assert len(_drafts(client, auth)) == before


# --- device tokens ------------------------------------------------------------


def test_device_token_create_shape(client, auth):
    body = _mint(client, auth, "Kitchen iPad")
    assert set(body.keys()) == {"id", "label", "token"}
    assert body["label"] == "Kitchen iPad"
    assert body["token"].startswith("adt_")
    assert len(body["token"]) == len("adt_") + 43  # token_urlsafe(32)


def test_device_token_blank_label_422(client, auth):
    resp = client.post(f"{API}/auth/device-tokens", json={"label": "  "}, headers=auth)
    assert resp.status_code == 422


def test_device_token_list_hides_plaintext(client, auth):
    minted = _mint(client, auth, "ListMe")
    rows = client.get(f"{API}/auth/device-tokens", headers=auth).json()
    row = next(r for r in rows if r["id"] == minted["id"])
    assert set(row.keys()) == {"id", "label", "created_at", "last_used_at", "revoked_at"}
    assert row["label"] == "ListMe"
    assert row["revoked_at"] is None
    assert minted["token"] not in str(rows)


def test_device_token_endpoints_require_jwt(client, auth):
    minted = _mint(client, auth, "SelfLocked")
    device = {"Authorization": f"Bearer {minted['token']}"}
    # A capture token can never manage tokens (mint itself an army, list, revoke).
    assert client.get(f"{API}/auth/device-tokens", headers=device).status_code == 401
    assert client.post(
        f"{API}/auth/device-tokens", json={"label": "evil"}, headers=device
    ).status_code == 401
    assert client.post(
        f"{API}/auth/device-tokens/{minted['id']}/revoke", headers=device
    ).status_code == 401


def test_capture_with_device_token_and_last_used_at(client, auth):
    minted = _mint(client, auth, "Phone")
    device = {"Authorization": f"Bearer {minted['token']}"}

    resp = _capture(client, device, _jpeg((6, 7, 8)))
    assert resp.status_code == 201, resp.text
    assert resp.json()["entity"]["draft"] is True

    rows = client.get(f"{API}/auth/device-tokens", headers=auth).json()
    row = next(r for r in rows if r["id"] == minted["id"])
    assert row["last_used_at"] is not None


def test_device_token_revoke_kills_auth(client, auth):
    minted = _mint(client, auth, "Revoked")
    device = {"Authorization": f"Bearer {minted['token']}"}
    assert _capture(client, device, _jpeg((7, 8, 9))).status_code == 201

    assert client.post(
        f"{API}/auth/device-tokens/{minted['id']}/revoke", headers=auth
    ).status_code == 204
    assert _capture(client, device, _jpeg((8, 9, 10))).status_code == 401
    # Revoke is idempotent; unknown ids 404.
    assert client.post(
        f"{API}/auth/device-tokens/{minted['id']}/revoke", headers=auth
    ).status_code == 204
    assert client.post(
        f"{API}/auth/device-tokens/999999/revoke", headers=auth
    ).status_code == 404


def test_expired_device_token_rejected(client, auth):
    from datetime import timedelta

    from app.database import get_sessionmaker
    from app.models.auth import DeviceToken
    from app.utils.dt import utcnow

    minted = _mint(client, auth, "Expired")
    with get_sessionmaker()() as db:
        token = db.get(DeviceToken, minted["id"])
        token.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()

    device = {"Authorization": f"Bearer {minted['token']}"}
    assert _capture(client, device, _jpeg((9, 10, 11))).status_code == 401


def test_garbage_device_token_401(client):
    device = {"Authorization": "Bearer adt_definitely-not-a-real-token"}
    assert _capture(client, device, _jpeg((10, 11, 12))).status_code == 401


def test_capture_token_scope_wall(client, auth):
    """A capture token must be rejected on EVERY endpoint outside its scope."""
    minted = _mint(client, auth, "Walled")
    device = {"Authorization": f"Bearer {minted['token']}"}
    victim = _make(client, auth, "WallVictim", "space")
    att = client.post(
        f"{API}/entities/{victim['id']}/attachments",
        files={"file": ("wall.jpg", _jpeg((26, 27, 28)), "image/jpeg")},
        headers=auth,
    )
    assert att.status_code == 201, att.text
    att = att.json()

    blocked = [
        ("GET", f"{API}/entities/tree", None),
        ("GET", f"{API}/entities/{victim['id']}", None),
        ("GET", f"{API}/search?q=wall", None),
        ("GET", f"{API}/admin/backups", None),
        ("GET", f"{API}/admin/export.csv", None),
        ("DELETE", f"{API}/entities/{victim['id']}", None),
        ("GET", f"{API}/intake/drafts", None),
        ("POST", f"{API}/intake/promote", {"entity_ids": [victim["id"]]}),
        ("GET", f"{API}/presets", None),
        ("POST", f"{API}/entities", {"name": "X", "kind": "space"}),
        # Upload is capture-scope, but nothing else about attachments is.
        ("PATCH", f"{API}/attachments/{att['id']}", {"title": "hacked"}),
        ("DELETE", f"{API}/attachments/{att['id']}", None),
        ("PUT", f"{API}/entities/{victim['id']}/cover", {"attachment_id": att["id"]}),
        ("PUT", f"{API}/entities/{victim['id']}/tags", {"tags": ["hacked"]}),
        ("GET", f"{API}/auth/me", None),
        ("PATCH", f"{API}/entities/{victim['id']}", {"name": "Hacked"}),
        ("POST", f"{API}/entities/{victim['id']}/asset-tag", {"auto": True}),
        ("GET", f"{API}/labels/batches", None),
        ("GET", f"{API}/inventory/low-stock", None),
        # The adt_ plaintext must never trade up to a JWT session.
        ("POST", f"{API}/auth/refresh", {"refresh_token": minted["token"]}),
    ]
    for method, url, body in blocked:
        resp = client.request(method, url, json=body, headers=device)
        assert resp.status_code in (401, 403), f"{method} {url} -> {resp.status_code}"

    # The blocked writes really did nothing.
    fresh = _get(client, auth, victim["id"])
    assert fresh["name"] == "WallVictim"
    assert fresh["asset_tag"] is None
    assert fresh["tags"] == []
    rows = client.get(f"{API}/entities/{victim['id']}/attachments", headers=auth).json()
    assert [a["id"] for a in rows] == [att["id"]]
    assert rows[0]["title"] is None


def test_capture_token_allowed_on_resolve_and_attachment_upload(client, auth):
    minted = _mint(client, auth, "Allowed")
    device = {"Authorization": f"Bearer {minted['token']}"}
    shelf = _make(client, auth, "CapShelf", "space")

    # POST /entities/{id}/attachments works with the device token...
    resp = client.post(
        f"{API}/entities/{shelf['id']}/attachments",
        files={"file": ("p.jpg", _jpeg((11, 12, 13)), "image/jpeg")},
        headers=device,
    )
    assert resp.status_code == 201, resp.text
    # ...but listing attachments stays JWT-only.
    assert client.get(
        f"{API}/entities/{shelf['id']}/attachments", headers=device
    ).status_code == 401

    # GET /labels/resolve accepts the device token: an unknown tag 404s (the
    # handler ran) where the same call without auth 401s before any lookup.
    # No tag is MINTED here on purpose — test_io's exact-header tests (later in
    # the session) rely on no entity asset tags existing yet.
    assert client.get(f"{API}/labels/resolve/ZZ-9999").status_code == 401
    assert client.get(f"{API}/labels/resolve/ZZ-9999", headers=device).status_code == 404


def test_device_token_resolve_returns_slim_entity(client, auth):
    """A resolved tag gives JWT callers the full EntityOut but device-token
    callers only a slim {id,name,kind,breadcrumb,asset_tag,thumb_url} — a
    leaked phone token must never read purchase prices, serials or notes.

    The asset tag minted here is CLEARED at the end: test_io's exact-header
    tests (later in the session) rely on no entity asset tags existing."""
    minted = _mint(client, auth, "SlimResolver")
    device = {"Authorization": f"Bearer {minted['token']}"}
    shelf = _make(client, auth, "SlimShelf", "space")
    item = _make(client, auth, "SlimItem", "item", parent_id=shelf["id"])
    resp = client.post(
        f"{API}/entities/{item['id']}/asset-tag", json={"tag": "ZZ-SLIM"}, headers=auth
    )
    assert resp.status_code == 200, resp.text

    # Device token: slim shape, nothing more (scan is case-insensitive).
    resp = client.get(f"{API}/labels/resolve/zz-slim", headers=device)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "entity"
    slim = body["entity"]
    assert set(slim.keys()) == {"id", "name", "kind", "breadcrumb", "asset_tag", "thumb_url"}
    assert slim["id"] == item["id"]
    assert slim["name"] == "SlimItem"
    assert slim["kind"] == "item"
    assert slim["breadcrumb"] == "SlimShelf › SlimItem"
    assert slim["asset_tag"] == "ZZ-SLIM"
    assert slim["thumb_url"] is None  # no cover photo

    # JWT: the full EntityOut as before.
    resp = client.get(f"{API}/labels/resolve/ZZ-SLIM", headers=auth)
    assert resp.status_code == 200, resp.text
    full = resp.json()["entity"]
    assert full["id"] == item["id"]
    for key in ("purchase_price", "serial_number", "notes", "parent_id", "tags"):
        assert key in full, key

    # Restore the no-asset-tags invariant for the rest of the session.
    resp = client.post(
        f"{API}/entities/{item['id']}/asset-tag", json={"tag": None}, headers=auth
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_tag"] is None


def test_device_token_last_used_at_touch_throttled(client, auth):
    """Two captures back-to-back: the first stamps last_used_at, the second
    (well inside the 60s throttle window) must NOT rewrite it."""
    minted = _mint(client, auth, "Throttled")
    device = {"Authorization": f"Bearer {minted['token']}"}

    assert _capture(client, device, _jpeg((27, 28, 29))).status_code == 201
    rows = client.get(f"{API}/auth/device-tokens", headers=auth).json()
    first = next(r for r in rows if r["id"] == minted["id"])["last_used_at"]
    assert first is not None

    assert _capture(client, device, _jpeg((28, 29, 30))).status_code == 201
    rows = client.get(f"{API}/auth/device-tokens", headers=auth).json()
    second = next(r for r in rows if r["id"] == minted["id"])["last_used_at"]
    assert second == first


def test_device_token_expires_days(client, auth):
    from datetime import timedelta

    from app.database import get_sessionmaker
    from app.models.auth import DeviceToken
    from app.utils.dt import utcnow

    # Validation: zero/negative TTL and an over-long label are 422s.
    assert client.post(
        f"{API}/auth/device-tokens", json={"label": "Bad", "expires_days": 0}, headers=auth
    ).status_code == 422
    assert client.post(
        f"{API}/auth/device-tokens", json={"label": "x" * 256}, headers=auth
    ).status_code == 422

    resp = client.post(
        f"{API}/auth/device-tokens",
        json={"label": "Ephemeral", "expires_days": 1},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    minted = resp.json()
    device = {"Authorization": f"Bearer {minted['token']}"}
    # Not yet expired — works like any capture token.
    assert _capture(client, device, _jpeg((29, 30, 31))).status_code == 201

    with get_sessionmaker()() as db:
        token = db.get(DeviceToken, minted["id"])
        assert token.expires_at is not None  # expires_days actually landed
        token.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert _capture(client, device, _jpeg((30, 31, 32))).status_code == 401


# --- drafts listing -----------------------------------------------------------


def test_drafts_listing_newest_first(client, auth):
    e1 = _capture(client, auth, _jpeg((12, 13, 14)), name="Older draft").json()["entity"]
    e2 = _capture(client, auth, _jpeg((13, 14, 15)), name="Newer draft").json()["entity"]

    drafts = _drafts(client, auth)
    assert all(d["draft"] for d in drafts)
    ids = [d["id"] for d in drafts]
    assert ids.index(e2["id"]) < ids.index(e1["id"])


def test_drafts_visible_outside_inbox_too(client, auth):
    """A moved draft (not yet promoted) still shows in the pile."""
    e = _capture(client, auth, _jpeg((14, 15, 16))).json()["entity"]
    closet = _make(client, auth, "DraftCloset", "space")
    resp = client.post(
        f"{API}/entities/{e['id']}/move", json={"parent_id": closet["id"]}, headers=auth
    )
    assert resp.status_code == 200
    row = next(d for d in _drafts(client, auth) if d["id"] == e["id"])
    assert row["parent_id"] == closet["id"]
    assert row["draft"] is True


def test_drafts_inside_archived_subtree_hidden(client, auth):
    """Same archived-subtree predicate as tree listing and search: a draft in
    an archived container disappears from the pile and comes back on unarchive."""
    e = _capture(client, auth, _jpeg((31, 32, 33))).json()["entity"]
    attic = _make(client, auth, "DraftAttic", "space")
    resp = client.post(
        f"{API}/entities/{e['id']}/move", json={"parent_id": attic["id"]}, headers=auth
    )
    assert resp.status_code == 200
    assert e["id"] in [d["id"] for d in _drafts(client, auth)]

    assert client.post(f"{API}/entities/{attic['id']}/archive", headers=auth).status_code == 200
    assert e["id"] not in [d["id"] for d in _drafts(client, auth)]
    # Still a draft — hidden, not promoted or deleted.
    assert _get(client, auth, e["id"])["draft"] is True

    assert client.post(f"{API}/entities/{attic['id']}/unarchive", headers=auth).status_code == 200
    assert e["id"] in [d["id"] for d in _drafts(client, auth)]


# --- promote ------------------------------------------------------------------


def test_promote_single_moves_and_clears_draft(client, auth):
    e = _capture(client, auth, _jpeg((15, 16, 17))).json()["entity"]
    shelf = _make(client, auth, "PromoShelf", "space")

    resp = _promote(client, auth, {"entity_ids": [e["id"]], "parent_id": shelf["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["errors"] == []
    [row] = body["promoted"]
    assert row["id"] == e["id"]
    assert row["parent_id"] == shelf["id"]
    assert row["draft"] is False
    assert e["id"] not in [d["id"] for d in _drafts(client, auth)]


def test_promote_batch_category_and_tags_replace(client, auth):
    e1 = _capture(client, auth, _jpeg((16, 17, 18))).json()["entity"]
    e2 = _capture(client, auth, _jpeg((17, 18, 19))).json()["entity"]
    box = _make(client, auth, "PromoBox", "space")
    cat = client.post(f"{API}/categories", json={"name": "IntakeCat"}, headers=auth)
    assert cat.status_code == 201, cat.text
    cat = cat.json()
    # e1 already carries a tag — promote REPLACES the whole set.
    assert client.put(
        f"{API}/entities/{e1['id']}/tags", json={"tags": ["pre-existing"]}, headers=auth
    ).status_code == 200

    resp = _promote(
        client,
        auth,
        {
            "entity_ids": [e1["id"], e2["id"]],
            "parent_id": box["id"],
            "category_id": cat["id"],
            "tags": ["intake", "m7"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["errors"] == []
    assert {r["id"] for r in body["promoted"]} == {e1["id"], e2["id"]}
    for row in body["promoted"]:
        assert row["parent_id"] == box["id"]
        assert row["category_id"] == cat["id"]
        assert sorted(t["name"] for t in row["tags"]) == ["intake", "m7"]
        assert row["draft"] is False


def test_promote_explicit_null_category_clears(client, auth):
    e = _capture(client, auth, _jpeg((18, 19, 20))).json()["entity"]
    cat = client.post(f"{API}/categories", json={"name": "ClearMeCat"}, headers=auth).json()
    client.patch(f"{API}/entities/{e['id']}", json={"category_id": cat["id"]}, headers=auth)

    resp = _promote(client, auth, {"entity_ids": [e["id"]], "category_id": None})
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["promoted"]
    assert row["category_id"] is None
    assert row["draft"] is False


def test_promote_without_category_key_keeps_it(client, auth):
    e = _capture(client, auth, _jpeg((19, 20, 21))).json()["entity"]
    cat = client.post(f"{API}/categories", json={"name": "KeepMeCat"}, headers=auth).json()
    client.patch(f"{API}/entities/{e['id']}", json={"category_id": cat["id"]}, headers=auth)

    resp = _promote(client, auth, {"entity_ids": [e["id"]]})
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["promoted"]
    assert row["category_id"] == cat["id"]
    assert row["draft"] is False


def test_promote_error_isolation_non_draft_untouched(client, auth):
    """Promote files DRAFTS only: a non-draft in the batch is a per-entity
    error and stays fully untouched (name/tags/parent pinned) while the
    draft next to it is applied in full."""
    ok = _capture(client, auth, _jpeg((20, 21, 22))).json()["entity"]
    room = _make(client, auth, "IsoRoom", "space")
    desk = _make(client, auth, "IsoDesk", "furniture", parent_id=room["id"])
    rogue = _make(client, auth, "IsoRogueSpace", "space")  # never captured -> not a draft
    assert client.put(
        f"{API}/entities/{rogue['id']}/tags", json={"tags": ["keepme"]}, headers=auth
    ).status_code == 200

    resp = _promote(
        client,
        auth,
        {
            "entity_ids": [ok["id"], rogue["id"]],
            "parent_id": desk["id"],
            "tags": ["filed"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [r["id"] for r in body["promoted"]] == [ok["id"]]
    [err] = body["errors"]
    assert err["entity_id"] == rogue["id"]
    assert "is not a draft" in err["message"]

    filed = _get(client, auth, ok["id"])
    assert filed["parent_id"] == desk["id"]
    assert filed["draft"] is False
    assert [t["name"] for t in filed["tags"]] == ["filed"]

    untouched = _get(client, auth, rogue["id"])
    assert untouched["name"] == "IsoRogueSpace"
    assert untouched["parent_id"] is None
    assert [t["name"] for t in untouched["tags"]] == ["keepme"]


def test_promote_duplicate_ids_single_row(client, auth):
    """Duplicate ids collapse (first occurrence wins) — one promoted row, no
    bogus 'already promoted' error for the second mention."""
    e = _capture(client, auth, _jpeg((32, 33, 34))).json()["entity"]
    shelf = _make(client, auth, "DupeShelf", "space")

    resp = _promote(
        client, auth, {"entity_ids": [e["id"], e["id"], e["id"]], "parent_id": shelf["id"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["errors"] == []
    assert [r["id"] for r in body["promoted"]] == [e["id"]]
    assert body["promoted"][0]["draft"] is False


def test_promote_inbox_itself_is_per_row_error(client, auth):
    """The protected Inbox in the id list is a per-entity error (never moved),
    isolated from the draft next to it."""
    inbox = _inbox(client, auth)
    e = _capture(client, auth, _jpeg((33, 34, 35))).json()["entity"]
    shelf = _make(client, auth, "InboxGuardShelf", "space")

    resp = _promote(
        client, auth, {"entity_ids": [inbox["id"], e["id"]], "parent_id": shelf["id"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [r["id"] for r in body["promoted"]] == [e["id"]]
    [err] = body["errors"]
    assert err["entity_id"] == inbox["id"]
    assert "Inbox" in err["message"]

    # The Inbox itself really did not move.
    fresh = _get(client, auth, inbox["id"])
    assert fresh["protected"] is True
    assert fresh["parent_id"] is None


def test_promote_unknown_entity_is_per_row_error(client, auth):
    e = _capture(client, auth, _jpeg((21, 22, 23))).json()["entity"]
    resp = _promote(client, auth, {"entity_ids": [999999, e["id"]]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [r["id"] for r in body["promoted"]] == [e["id"]]
    [err] = body["errors"]
    assert err["entity_id"] == 999999
    assert "not found" in err["message"]


def test_promote_unknown_parent_404(client, auth):
    e = _capture(client, auth, _jpeg((22, 23, 24))).json()["entity"]
    resp = _promote(client, auth, {"entity_ids": [e["id"]], "parent_id": 999999})
    assert resp.status_code == 404
    # 404 aborted the batch — still a draft.
    assert _get(client, auth, e["id"])["draft"] is True


def test_promote_unknown_category_404(client, auth):
    e = _capture(client, auth, _jpeg((23, 24, 25))).json()["entity"]
    resp = _promote(client, auth, {"entity_ids": [e["id"]], "category_id": 999999})
    assert resp.status_code == 404
    assert _get(client, auth, e["id"])["draft"] is True


def test_promote_to_archived_parent_allowed(client, auth):
    e = _capture(client, auth, _jpeg((24, 25, 26))).json()["entity"]
    attic = _make(client, auth, "PromoAttic", "space")
    assert client.post(f"{API}/entities/{attic['id']}/archive", headers=auth).status_code == 200

    resp = _promote(client, auth, {"entity_ids": [e["id"]], "parent_id": attic["id"]})
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["promoted"]
    assert row["parent_id"] == attic["id"]
    assert row["draft"] is False


def test_promote_into_inbox_allowed_draft_still_cleared(client, auth):
    inbox = _inbox(client, auth)
    e = _capture(client, auth, _jpeg((25, 26, 27))).json()["entity"]

    resp = _promote(client, auth, {"entity_ids": [e["id"]], "parent_id": inbox["id"]})
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["promoted"]
    assert row["parent_id"] == inbox["id"]
    assert row["draft"] is False


def test_promote_all_remaining_drafts_inbox_zero(client, auth):
    """Runs LAST: files every draft left over from the whole module."""
    leftovers = [d["id"] for d in _drafts(client, auth)]
    assert leftovers, "earlier tests should have left drafts behind"
    dump = _make(client, auth, "TriageDump", "space")

    resp = _promote(client, auth, {"entity_ids": leftovers, "parent_id": dump["id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["errors"] == []
    assert _drafts(client, auth) == []
