"""M4 search tests: FTS5 hits per column, trigger-kept sync, ranking, filters,
MATCH injection hardening, index rebuild."""

import io

import pytest
from PIL import Image

API = "/api/v1"


@pytest.fixture(scope="module")
def auth(client, test_user):
    """One login for the whole module (same pattern as test_tree)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _entity(client, auth, name, kind="space", parent_id=None, **extra):
    resp = client.post(
        f"{API}/entities",
        json={"name": name, "kind": kind, "parent_id": parent_id, **extra},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _search(client, auth, **params):
    resp = client.get(f"{API}/search", params=params, headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


def _ids(results):
    return [r["id"] for r in results]


def _jpeg(size=(64, 48), color=(10, 90, 10)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


# --- basic hits & ranking -----------------------------------------------------


def test_search_requires_auth(client):
    assert client.get(f"{API}/search").status_code == 401


def test_search_shape_is_entity_out(client, auth):
    e = _entity(client, auth, "Shapephone")
    results = _search(client, auth, q="shapephone")
    row = next(r for r in results if r["id"] == e["id"])
    assert row["breadcrumb"] == "Shapephone"
    assert row["tags"] == []
    assert "child_count" in row and "thumb_url" in row


def test_search_name_prefix_hit(client, auth):
    e = _entity(client, auth, "Smartphone")
    assert e["id"] in _ids(_search(client, auth, q="smar"))
    assert e["id"] in _ids(_search(client, auth, q="Smartphone"))
    assert e["id"] not in _ids(_search(client, auth, q="smartphonex"))


def test_search_description_hit(client, auth):
    e = _entity(client, auth, "DescHolder", description="coated in unobtanium alloy")
    assert e["id"] in _ids(_search(client, auth, q="unobtanium"))


def test_search_breadcrumb_hit_ranks_name_match_first(client, auth):
    root = _entity(client, auth, "Kellergeschoss")
    child = _entity(client, auth, "Rohrzange", kind="item", parent_id=root["id"])
    results = _search(client, auth, q="kellergeschoss")
    ids = _ids(results)
    assert root["id"] in ids and child["id"] in ids  # child hits via breadcrumb
    assert ids.index(root["id"]) < ids.index(child["id"])  # name(10) > breadcrumb(3)


def test_search_diacritics_insensitive(client, auth):
    e = _entity(client, auth, "Café Grinder")
    assert e["id"] in _ids(_search(client, auth, q="cafe"))
    assert e["id"] in _ids(_search(client, auth, q="café"))


def test_search_asset_tag_hit(client, auth):
    from app.database import get_sessionmaker
    from app.models.entity import Entity

    e = _entity(client, auth, "Tagged Beast")
    with get_sessionmaker()() as db:
        db.get(Entity, e["id"]).asset_tag = "ZQAT-777"
        db.commit()  # entity AU trigger must index the new asset_tag
    assert e["id"] in _ids(_search(client, auth, q="zqat"))
    assert e["id"] in _ids(_search(client, auth, q="ZQAT-777"))


def test_bm25_column_weight_order(client, auth):
    from app.database import get_sessionmaker
    from app.models.entity import Entity

    # asset_tag (16) vs name (10, which always co-hits breadcrumb, +3): equal
    # total token counts so only the column weights decide, not doc length.
    a = _entity(client, auth, "Weightprobe Alpha")
    b = _entity(client, auth, "Zephyrion Gadget Deluxe")
    with get_sessionmaker()() as db:  # asset_tag has no API yet — set it directly
        db.get(Entity, a["id"]).asset_tag = "ZEPHYRION-01"
        db.commit()
    ids = _ids(_search(client, auth, q="zephyrion"))
    assert a["id"] in ids and b["id"] in ids
    assert ids.index(a["id"]) < ids.index(b["id"])  # asset_tag(16) > name+breadcrumb(13)

    # tags (6) vs fields (4).
    c = _entity(client, auth, "Weightprobe Charlie")
    d = _entity(client, auth, "Weightprobe Delta")
    resp = client.put(
        f"{API}/entities/{c['id']}/tags", json={"tags": ["Quibblemark"]}, headers=auth
    )
    assert resp.status_code == 200
    resp = client.post(
        f"{API}/fields", json={"name": "Weightfield", "type": "text"}, headers=auth
    )
    assert resp.status_code == 201
    field_def = resp.json()
    resp = client.put(
        f"{API}/entities/{d['id']}/fields",
        json={"values": [{"field_def_id": field_def["id"], "value": "Quibblemark"}]},
        headers=auth,
    )
    assert resp.status_code == 200
    ids = _ids(_search(client, auth, q="quibblemark"))
    assert c["id"] in ids and d["id"] in ids
    assert ids.index(c["id"]) < ids.index(d["id"])  # tags(6) > fields(4)


# --- trigger-kept sync --------------------------------------------------------


def test_rename_and_move_keep_fts_in_sync(client, auth):
    root_a = _entity(client, auth, "Vulkanberg")
    root_b = _entity(client, auth, "Talstation")
    child = _entity(client, auth, "Lavaprobe", kind="item", parent_id=root_a["id"])

    assert child["id"] in _ids(_search(client, auth, q="vulkanberg"))  # breadcrumb

    # Move: the subtree rewrite must re-index the breadcrumb.
    resp = client.post(
        f"{API}/entities/{child['id']}/move", json={"parent_id": root_b["id"]}, headers=auth
    )
    assert resp.status_code == 200
    assert child["id"] not in _ids(_search(client, auth, q="vulkanberg"))
    assert child["id"] in _ids(_search(client, auth, q="talstation"))

    # Rename: both the renamed root and its subtree's breadcrumbs re-index.
    resp = client.patch(f"{API}/entities/{root_b['id']}", json={"name": "Bergstation"}, headers=auth)
    assert resp.status_code == 200
    assert _ids(_search(client, auth, q="talstation")) == []
    found = _ids(_search(client, auth, q="bergstation"))
    assert root_b["id"] in found and child["id"] in found


def test_tag_set_rename_and_delete_keep_fts_in_sync(client, auth):
    e = _entity(client, auth, "Erbschrank")
    resp = client.put(
        f"{API}/entities/{e['id']}/tags", json={"tags": ["Sammlerstueck"]}, headers=auth
    )
    assert resp.status_code == 200
    assert e["id"] in _ids(_search(client, auth, q="sammlerstueck"))

    tag = next(t for t in client.get(f"{API}/tags", headers=auth).json()
               if t["name"] == "Sammlerstueck")
    assert client.patch(
        f"{API}/tags/{tag['id']}", json={"name": "Erbstueck"}, headers=auth
    ).status_code == 200
    assert _ids(_search(client, auth, q="sammlerstueck")) == []
    assert e["id"] in _ids(_search(client, auth, q="erbstueck"))

    assert client.delete(f"{API}/tags/{tag['id']}", headers=auth).status_code == 204
    assert _ids(_search(client, auth, q="erbstueck")) == []


def test_field_values_and_def_rename_keep_fts_in_sync(client, auth):
    resp = client.post(
        f"{API}/fields", json={"name": "Farbcode", "type": "text"}, headers=auth
    )
    assert resp.status_code == 201
    field_def = resp.json()
    e = _entity(client, auth, "Lackdose")
    resp = client.put(
        f"{API}/entities/{e['id']}/fields",
        json={"values": [{"field_def_id": field_def["id"], "value": "Ultramarin"}]},
        headers=auth,
    )
    assert resp.status_code == 200

    # Both the def NAME and the value are searchable.
    assert e["id"] in _ids(_search(client, auth, q="farbcode"))
    assert e["id"] in _ids(_search(client, auth, q="ultramarin"))

    assert client.patch(
        f"{API}/fields/{field_def['id']}", json={"name": "Farbwert"}, headers=auth
    ).status_code == 200
    assert _ids(_search(client, auth, q="farbcode")) == []
    assert e["id"] in _ids(_search(client, auth, q="farbwert"))

    # Clearing the value de-indexes it.
    resp = client.put(
        f"{API}/entities/{e['id']}/fields", json={"values": []}, headers=auth
    )
    assert resp.status_code == 200
    assert _ids(_search(client, auth, q="ultramarin")) == []


def test_deleted_entity_leaves_the_index(client, auth):
    root = _entity(client, auth, "DelIdx Root")
    e = _entity(client, auth, "Verdampferglas", kind="item", parent_id=root["id"])
    assert e["id"] in _ids(_search(client, auth, q="verdampferglas"))
    assert client.delete(f"{API}/entities/{e['id']}", headers=auth).status_code == 204
    assert _ids(_search(client, auth, q="verdampferglas")) == []


# --- filters ------------------------------------------------------------------


def test_search_kind_and_category_filters(client, auth):
    resp = client.post(f"{API}/categories", json={"name": "SearchCat"}, headers=auth)
    assert resp.status_code == 201
    cat = resp.json()
    root = _entity(client, auth, "Klangraum")
    item = _entity(client, auth, "Klangschale", kind="item", parent_id=root["id"])
    client.patch(f"{API}/entities/{item['id']}", json={"category_id": cat["id"]}, headers=auth)

    assert set(_ids(_search(client, auth, q="klang"))) >= {root["id"], item["id"]}
    assert _ids(_search(client, auth, q="klang", kind="item")) == [item["id"]]
    assert _ids(_search(client, auth, q="klang", category_id=cat["id"])) == [item["id"]]
    assert _ids(_search(client, auth, q="klang", kind="furniture")) == []


def test_search_tags_are_anded(client, auth):
    a = _entity(client, auth, "Tagsuche Eins")
    b = _entity(client, auth, "Tagsuche Zwei")
    client.put(f"{API}/entities/{a['id']}/tags", json={"tags": ["TSAlpha", "TSBeta"]}, headers=auth)
    client.put(f"{API}/entities/{b['id']}/tags", json={"tags": ["TSAlpha"]}, headers=auth)

    assert set(_ids(_search(client, auth, q="tagsuche", tags="TSAlpha"))) == {a["id"], b["id"]}
    assert _ids(_search(client, auth, q="tagsuche", tags="TSAlpha,TSBeta")) == [a["id"]]
    assert _ids(_search(client, auth, q="tagsuche", tags="tsalpha,tsbeta")) == [a["id"]]  # NOCASE
    assert _ids(_search(client, auth, q="tagsuche", tags="TSGamma")) == []
    # Pure tag browse without q.
    assert _ids(_search(client, auth, tags="TSAlpha,TSBeta")) == [a["id"]]


def test_search_under_subtree_filter(client, auth):
    root_a = _entity(client, auth, "Under Root A")
    root_b = _entity(client, auth, "Under Root B")
    in_a = _entity(client, auth, "Quarzfilter A", kind="item", parent_id=root_a["id"])
    in_b = _entity(client, auth, "Quarzfilter B", kind="item", parent_id=root_b["id"])

    both = _ids(_search(client, auth, q="quarzfilter"))
    assert in_a["id"] in both and in_b["id"] in both
    assert _ids(_search(client, auth, q="quarzfilter", under=root_a["id"])) == [in_a["id"]]
    resp = client.get(f"{API}/search", params={"q": "quarzfilter", "under": 999999}, headers=auth)
    assert resp.status_code == 404


def test_search_has_photo_filter(client, auth):
    root = _entity(client, auth, "Foto Root")
    with_photo = _entity(client, auth, "Fotofilter Mit", kind="item", parent_id=root["id"])
    without = _entity(client, auth, "Fotofilter Ohne", kind="item", parent_id=root["id"])
    assert client.post(
        f"{API}/entities/{with_photo['id']}/attachments",
        files={"file": ("p.jpg", _jpeg(), "application/octet-stream")},
        headers=auth,
    ).status_code == 201

    assert _ids(_search(client, auth, q="fotofilter", has_photo=True)) == [with_photo["id"]]
    assert _ids(_search(client, auth, q="fotofilter", has_photo=False)) == [without["id"]]


def test_search_archived_subtree_hidden(client, auth):
    root = _entity(client, auth, "Archiv Root")
    box = _entity(client, auth, "Archiv Box", kind="container", parent_id=root["id"])
    item = _entity(client, auth, "Xylographit", kind="item", parent_id=box["id"])
    assert client.post(f"{API}/entities/{box['id']}/archive", headers=auth).status_code == 200

    # The archived box AND its live item hide together (tree semantics).
    assert _ids(_search(client, auth, q="xylographit")) == []
    assert _ids(_search(client, auth, q="archiv", kind="container")) == []
    found = _ids(_search(client, auth, q="xylographit", include_archived=True))
    assert item["id"] in found


def test_search_under_archived_anchor(client, auth):
    root = _entity(client, auth, "UnderArch Root")
    box = _entity(client, auth, "UnderArch Box", kind="container", parent_id=root["id"])
    item = _entity(client, auth, "UnderArch Item", kind="item", parent_id=box["id"])
    assert client.post(f"{API}/entities/{box['id']}/archive", headers=auth).status_code == 200

    # Default flags: the archived anchor hides its whole subtree.
    assert _ids(_search(client, auth, under=box["id"])) == []
    # include_archived surfaces the subtree, anchor included.
    found = _ids(_search(client, auth, under=box["id"], include_archived=True))
    assert set(found) == {box["id"], item["id"]}


def test_search_without_q_is_name_ordered_browse(client, auth):
    root = _entity(client, auth, "Browse Root")
    b = _entity(client, auth, "Browse Bravo", kind="item", parent_id=root["id"])
    a = _entity(client, auth, "Browse Alpha", kind="item", parent_id=root["id"])
    results = _search(client, auth, under=root["id"], kind="item")
    assert _ids(results) == [a["id"], b["id"]]  # lower(name) order, no bm25


def test_search_limit(client, auth):
    root = _entity(client, auth, "Limit Root")
    for i in range(4):
        _entity(client, auth, f"Limitwidget {i}", kind="item", parent_id=root["id"])
    assert len(_search(client, auth, q="limitwidget", limit=2)) == 2
    assert len(_search(client, auth, q="limitwidget")) == 4


# --- hardening ----------------------------------------------------------------


@pytest.mark.parametrize(
    "evil",
    ['"', 'NEAR(', 'OR', 'AND', 'NOT', '*', 'a"b', '"unbalanced', '(paren)', '-',
     'name:x', '^caret', '{brace}', "col : val OR 1"],
)
def test_match_injection_attempts_return_200(client, auth, evil):
    resp = client.get(f"{API}/search", params={"q": evil}, headers=auth)
    assert resp.status_code == 200, f"{evil!r}: {resp.text}"
    assert "results" in resp.json()


def test_rebuild_search_restores_after_corruption(client, auth):
    from sqlalchemy import text

    from app.database import get_sessionmaker

    e = _entity(client, auth, "Wiederaufbau Probe")
    assert e["id"] in _ids(_search(client, auth, q="wiederaufbau"))

    with get_sessionmaker()() as db:
        db.execute(text("DELETE FROM search_fts"))
        db.commit()
    assert _ids(_search(client, auth, q="wiederaufbau")) == []

    resp = client.post(f"{API}/admin/rebuild-search", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["indexed"] > 0
    assert e["id"] in _ids(_search(client, auth, q="wiederaufbau"))
    # Tag/field columns rebuilt too, not just the entity columns.
    tagged = _entity(client, auth, "Wiederaufbau Tagged")
    client.put(f"{API}/entities/{tagged['id']}/tags", json={"tags": ["RebuildTag"]}, headers=auth)
    with get_sessionmaker()() as db:
        db.execute(text("DELETE FROM search_fts"))
        db.commit()
    client.post(f"{API}/admin/rebuild-search", headers=auth)
    assert tagged["id"] in _ids(_search(client, auth, q="rebuildtag"))


def test_rebuild_requires_auth(client):
    assert client.post(f"{API}/admin/rebuild-search").status_code == 401
