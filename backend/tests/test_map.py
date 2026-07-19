"""M8 house-map tests: floor plans, room regions, furniture grids, cell binds.

Image fixtures are generated in code with Pillow (same approach as
test_attachments); every floor image gets a UNIQUE color so content-addressed
refcounting stays independent between tests — except where sharing is the point.
"""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

API = "/api/v1"


@pytest.fixture(scope="module")
def auth(client, test_user):
    """One login for the whole module (same pattern as test_attachments)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _entity(client, auth, name, kind, parent_id=None):
    resp = client.post(
        f"{API}/entities",
        json={"name": name, "kind": kind, "parent_id": parent_id},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _jpeg(color, size=(800, 600)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _post_floor(client, auth, entity_id, data):
    return client.post(
        f"{API}/map/floors",
        files={"file": ("plan.jpg", data, "image/jpeg")},
        data={"entity_id": str(entity_id)},
        headers=auth,
    )


def _floor(client, auth, entity_id, data):
    resp = _post_floor(client, auth, entity_id, data)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _post_blank_floor(client, auth, entity_id, **canvas):
    return client.post(
        f"{API}/map/floors", json={"entity_id": entity_id, **canvas}, headers=auth
    )


def _blank_floor(client, auth, entity_id, **canvas):
    resp = _post_blank_floor(client, auth, entity_id, **canvas)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _put_placement(client, auth, floor_id, entity_id, payload):
    return client.put(
        f"{API}/map/floors/{floor_id}/placements/{entity_id}", json=payload, headers=auth
    )


def _post_grid(client, auth, **payload):
    return client.post(f"{API}/map/grids", json=payload, headers=auth)


def _grid(client, auth, **payload):
    resp = _post_grid(client, auth, **payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _cell_at(grid, row, col):
    return next(c for c in grid["cells"] if (c["row"], c["col"]) == (row, col))


def _bind(client, auth, cell_id, payload):
    return client.post(f"{API}/map/cells/{cell_id}/bind", json=payload, headers=auth)


def _data_dir() -> Path:
    from app.config import get_settings

    return get_settings().data_dir


def _disk_path(image_url: str) -> Path:
    return _data_dir() / image_url.removeprefix("/media/")


def _fetch_image(client, url):
    resp = client.get(url)  # deliberately no auth headers: /media is public
    assert resp.status_code == 200, url
    return Image.open(io.BytesIO(resp.content))


TRIANGLE = [[0, 0], [100, 0], [100, 100]]


# --- auth ---------------------------------------------------------------------


def test_map_endpoints_require_auth(client):
    assert client.get(f"{API}/map/floors").status_code == 401
    assert client.post(f"{API}/map/grids", json={}).status_code == 401
    assert client.patch(f"{API}/map/cells/1", json={}).status_code == 401


# --- floors -------------------------------------------------------------------


def test_floor_create_shape_list_and_media(client, auth):
    space = _entity(client, auth, "MapHome", "space")
    floor = _floor(client, auth, space["id"], _jpeg((10, 20, 30)))

    assert set(floor.keys()) == {
        "id", "entity", "image_url", "image_w", "image_h", "sort_order",
        "region_count", "placement_count",
    }
    assert set(floor["entity"].keys()) == {"id", "name", "breadcrumb"}
    assert floor["entity"] == {"id": space["id"], "name": "MapHome", "breadcrumb": "MapHome"}
    assert (floor["image_w"], floor["image_h"]) == (800, 600)
    assert floor["sort_order"] == 0
    assert floor["region_count"] == 0
    assert floor["placement_count"] == 0
    assert floor["image_url"].startswith("/media/floorplans/")

    listed = client.get(f"{API}/map/floors", headers=auth).json()
    assert floor["id"] in [f["id"] for f in listed]

    served = client.get(floor["image_url"])  # no auth: /media is public by design
    assert served.status_code == 200
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert Image.open(io.BytesIO(served.content)).size == (800, 600)


def test_floor_create_rules_404_and_409(client, auth):
    space = _entity(client, auth, "MapRules", "space")
    furniture = _entity(client, auth, "MapRulesWardrobe", "furniture", space["id"])
    data = _jpeg((11, 21, 31))

    assert _post_floor(client, auth, 999999, data).status_code == 404
    assert _post_floor(client, auth, furniture["id"], data).status_code == 409

    _floor(client, auth, space["id"], data)
    assert _post_floor(client, auth, space["id"], data).status_code == 409  # duplicate


def test_blank_canvas_floor_create_defaults_and_custom(client, auth):
    s1 = _entity(client, auth, "BlankA", "space")
    floor = _blank_floor(client, auth, s1["id"])
    assert floor["image_url"] is None
    assert (floor["image_w"], floor["image_h"]) == (1600, 1200)
    assert floor["region_count"] == 0 and floor["placement_count"] == 0

    s2 = _entity(client, auth, "BlankB", "space")
    custom = _blank_floor(client, auth, s2["id"], canvas_w=2400, canvas_h=1800)
    assert (custom["image_w"], custom["image_h"]) == (2400, 1800)

    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert detail["image_url"] is None
    assert detail["regions"] == [] and detail["placements"] == []


def test_blank_canvas_floor_rules(client, auth):
    space = _entity(client, auth, "BlankRules", "space")
    furniture = _entity(client, auth, "BlankRulesWard", "furniture", space["id"])

    assert _post_blank_floor(client, auth, 999999).status_code == 404
    assert _post_blank_floor(client, auth, furniture["id"]).status_code == 409  # not a space
    # Out-of-range canvas: schema cap (422) at the router.
    assert _post_blank_floor(client, auth, space["id"], canvas_w=0).status_code == 422
    assert _post_blank_floor(client, auth, space["id"], canvas_w=99999).status_code == 422

    _blank_floor(client, auth, space["id"])
    assert _post_blank_floor(client, auth, space["id"]).status_code == 409  # duplicate


def test_blank_floor_add_then_remove_image_keeps_regions_and_placements(client, auth):
    space = _entity(client, auth, "BlankSwap", "space")
    room = _entity(client, auth, "BlankSwapRoom", "space", space["id"])
    ward = _entity(client, auth, "BlankSwapWard", "furniture", space["id"])
    floor = _blank_floor(client, auth, space["id"])  # 1600x1200 canvas, no image

    assert client.put(
        f"{API}/map/floors/{floor['id']}/regions/{room['id']}",
        json={"polygon": TRIANGLE},
        headers=auth,
    ).status_code == 200
    assert _put_placement(
        client, auth, floor["id"], ward["id"], {"x": 100, "y": 100, "w": 200, "h": 150}
    ).status_code == 200

    # Add an image to the blank canvas: dims stay the canvas frame (1600x1200).
    resp = client.patch(
        f"{API}/map/floors/{floor['id']}",
        files={"file": ("bg.jpg", _jpeg((60, 61, 62), size=(1000, 800)), "image/jpeg")},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    added = resp.json()
    assert (added["image_w"], added["image_h"]) == (1600, 1200)
    assert added["image_url"] is not None
    disk = _disk_path(added["image_url"])
    assert disk.exists()

    # Remove the image: back to blank canvas, file unlinked, layout untouched.
    resp = client.delete(f"{API}/map/floors/{floor['id']}/image", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["image_url"] is None
    assert not disk.exists(), "removed image is unlinked when unreferenced"

    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert [r["entity"]["id"] for r in detail["regions"]] == [room["id"]]
    assert [p["entity"]["id"] for p in detail["placements"]] == [ward["id"]]

    # Removing again is a harmless no-op.
    assert client.delete(f"{API}/map/floors/{floor['id']}/image", headers=auth).status_code == 200


def test_floor_image_capped_at_4000(client, auth):
    space = _entity(client, auth, "MapBig", "space")
    floor = _floor(client, auth, space["id"], _jpeg((12, 22, 32), size=(5000, 2500)))
    assert (floor["image_w"], floor["image_h"]) == (4000, 2000)
    assert _fetch_image(client, floor["image_url"]).size == (4000, 2000)


def test_floor_sort_order_patch_json_and_ordering(client, auth):
    s1 = _entity(client, auth, "MapSortA", "space")
    s2 = _entity(client, auth, "MapSortB", "space")
    f1 = _floor(client, auth, s1["id"], _jpeg((13, 23, 33)))
    f2 = _floor(client, auth, s2["id"], _jpeg((14, 24, 34)))

    resp = client.patch(f"{API}/map/floors/{f2['id']}", json={"sort_order": -1}, headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["sort_order"] == -1

    ids = [f["id"] for f in client.get(f"{API}/map/floors", headers=auth).json()]
    assert ids.index(f2["id"]) < ids.index(f1["id"])

    assert client.patch(
        f"{API}/map/floors/{f1['id']}", json={"sort_order": "abc"}, headers=auth
    ).status_code == 422
    assert client.patch(
        f"{API}/map/floors/999999", json={"sort_order": 1}, headers=auth
    ).status_code == 404


def test_floor_replace_image_keeps_regions(client, auth):
    space = _entity(client, auth, "MapSwap", "space")
    room = _entity(client, auth, "MapSwapRoom", "space", space["id"])
    floor = _floor(client, auth, space["id"], _jpeg((15, 25, 35)))
    old_path = _disk_path(floor["image_url"])
    assert client.put(
        f"{API}/map/floors/{floor['id']}/regions/{room['id']}",
        json={"polygon": TRIANGLE},
        headers=auth,
    ).status_code == 200

    resp = client.patch(
        f"{API}/map/floors/{floor['id']}",
        files={"file": ("new.jpg", _jpeg((16, 26, 36), size=(1000, 500)), "image/jpeg")},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    # The canvas frame is FIXED at creation (800x600) — an image swap keeps it so
    # regions/placements never shift, even though the new image is 1000x500.
    assert (updated["image_w"], updated["image_h"]) == (800, 600)
    assert updated["image_url"] != floor["image_url"]
    assert not old_path.exists(), "old image unreferenced after replace"
    assert _disk_path(updated["image_url"]).exists()

    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert [r["entity"]["id"] for r in detail["regions"]] == [room["id"]]


def test_floor_delete_cascades_regions_and_refcounted_file(client, auth):
    shared = _jpeg((17, 27, 37))  # identical bytes -> identical stored file
    sa_ = _entity(client, auth, "MapDelA", "space")
    room = _entity(client, auth, "MapDelARoom", "space", sa_["id"])
    sb = _entity(client, auth, "MapDelB", "space")
    fa = _floor(client, auth, sa_["id"], shared)
    fb = _floor(client, auth, sb["id"], shared)
    assert fa["image_url"] == fb["image_url"]
    disk = _disk_path(fa["image_url"])
    assert disk.exists()
    assert client.put(
        f"{API}/map/floors/{fa['id']}/regions/{room['id']}",
        json={"polygon": TRIANGLE},
        headers=auth,
    ).status_code == 200

    assert client.delete(f"{API}/map/floors/{fa['id']}", headers=auth).status_code == 204
    assert disk.exists(), "file still referenced by the other floor"
    assert fa["id"] not in [f["id"] for f in client.get(f"{API}/map/floors", headers=auth).json()]

    # Region rows are gone with the plan (FK cascade).
    from sqlalchemy import func, select

    from app.database import get_sessionmaker
    from app.models.map import MapRegion

    db = get_sessionmaker()()
    try:
        count = db.scalar(
            select(func.count(MapRegion.id)).where(MapRegion.floor_plan_id == fa["id"])
        )
    finally:
        db.close()
    assert count == 0

    assert client.delete(f"{API}/map/floors/{fb['id']}", headers=auth).status_code == 204
    assert not disk.exists(), "last floor out unlinks the shared image"
    assert client.delete(f"{API}/map/floors/{fa['id']}", headers=auth).status_code == 404


# --- regions ------------------------------------------------------------------


def test_region_validation(client, auth):
    space = _entity(client, auth, "MapRegVal", "space")
    room = _entity(client, auth, "MapRegValRoom", "space", space["id"])
    furniture = _entity(client, auth, "MapRegValShelf", "furniture", space["id"])
    other_root = _entity(client, auth, "MapRegValOther", "space")
    floor = _floor(client, auth, space["id"], _jpeg((18, 28, 38)))
    url = f"{API}/map/floors/{floor['id']}/regions"

    def put(entity_id, polygon):
        return client.put(f"{url}/{entity_id}", json={"polygon": polygon}, headers=auth)

    assert put(room["id"], [[0, 0], [10, 0]]).status_code == 422  # 2 points
    assert put(room["id"], [[0, 0], [900, 0], [100, 100]]).status_code == 409  # x > 805
    assert put(room["id"], [[0, -700], [10, 0], [20, 20]]).status_code == 409  # y < -5
    assert put(furniture["id"], TRIANGLE).status_code == 409  # not a space
    assert put(other_root["id"], TRIANGLE).status_code == 409  # not a descendant
    assert put(space["id"], TRIANGLE).status_code == 409  # the floor entity itself
    assert put(999999, TRIANGLE).status_code == 404
    assert client.put(
        f"{API}/map/floors/999999/regions/{room['id']}",
        json={"polygon": TRIANGLE},
        headers=auth,
    ).status_code == 404


def _put_region_raw(client, auth, floor_id, entity_id, payload):
    """PUT with plain-json encoding: httpx's json= refuses NaN/inf client-side
    (allow_nan=False), but a hostile client can still send the tokens — and
    both json.loads and pydantic floats accept them, so the SERVER must reject."""
    return client.put(
        f"{API}/map/floors/{floor_id}/regions/{entity_id}",
        content=json.dumps(payload),
        headers={**auth, "Content-Type": "application/json"},
    )


def test_region_label_anchor_and_finiteness_validation(client, auth):
    space = _entity(client, auth, "MapAnchor", "space")
    room = _entity(client, auth, "MapAnchorRoom", "space", space["id"])
    floor = _floor(client, auth, space["id"], _jpeg((24, 34, 44)))

    def put(payload):
        return _put_region_raw(client, auth, floor["id"], room["id"], payload)

    # Non-finite / out-of-bounds anchors are refused BEFORE commit — a stored
    # NaN/inf would 500 every floor-detail GET (JSONResponse allow_nan=False).
    assert put({"polygon": TRIANGLE, "label_x": float("inf"), "label_y": 10}).status_code == 409
    assert put({"polygon": TRIANGLE, "label_x": 10, "label_y": float("nan")}).status_code == 409
    assert put({"polygon": TRIANGLE, "label_x": 2000, "label_y": 10}).status_code == 409  # x > 805
    assert put({"polygon": TRIANGLE, "label_x": 10, "label_y": -700}).status_code == 409  # y < -5
    # NaN inside the polygon itself is rejected too.
    assert put({"polygon": [[0, 0], [100, 0], [float("nan"), 100]]}).status_code == 409
    # Schema cap: 501 points is beyond any hand-traced room.
    too_many = [[i % 100, i // 100] for i in range(501)]
    assert put({"polygon": too_many}).status_code == 422

    # Nothing was committed: the floor detail still serializes.
    resp = client.get(f"{API}/map/floors/{floor['id']}", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["regions"] == []


def test_region_upsert_update_and_delete(client, auth):
    space = _entity(client, auth, "MapRegUp", "space")
    room = _entity(client, auth, "MapRegUpRoom", "space", space["id"])
    floor = _floor(client, auth, space["id"], _jpeg((19, 29, 39)))
    url = f"{API}/map/floors/{floor['id']}/regions/{room['id']}"

    resp = client.put(url, json={"polygon": TRIANGLE}, headers=auth)
    assert resp.status_code == 200, resp.text
    region = resp.json()
    assert set(region.keys()) == {"id", "entity", "polygon", "label_x", "label_y"}
    assert set(region["entity"].keys()) == {"id", "name", "child_count", "item_count"}
    assert region["polygon"] == TRIANGLE
    assert region["label_x"] is None and region["label_y"] is None

    # Upsert: same row updated; slightly negative coords fall inside the tolerance.
    square = [[-3, -3], [200, 0], [200, 200], [0, 200]]
    resp = client.put(url, json={"polygon": square, "label_x": 90, "label_y": 80}, headers=auth)
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == region["id"]
    assert updated["polygon"] == square
    assert (updated["label_x"], updated["label_y"]) == (90, 80)

    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert detail["region_count"] == 1
    assert detail["regions"][0]["id"] == region["id"]

    assert client.delete(url, headers=auth).status_code == 204
    assert client.delete(url, headers=auth).status_code == 404


def test_region_item_counts_at_depth_with_archived_exclusion(client, auth):
    space = _entity(client, auth, "MapCount", "space")
    room = _entity(client, auth, "MapCountRoom", "space", space["id"])
    item_a = _entity(client, auth, "MapCountItemA", "item", room["id"])
    wardrobe = _entity(client, auth, "MapCountWardrobe", "furniture", room["id"])
    _entity(client, auth, "MapCountItemB", "item", wardrobe["id"])
    box = _entity(client, auth, "MapCountBox", "container", wardrobe["id"])
    _entity(client, auth, "MapCountItemD", "item", box["id"])
    room2 = _entity(client, auth, "MapCountRoom2", "space", space["id"])
    _entity(client, auth, "MapCountItemE", "item", room2["id"])

    floor = _floor(client, auth, space["id"], _jpeg((20, 30, 40)))
    for entity in (room, room2):
        assert client.put(
            f"{API}/map/floors/{floor['id']}/regions/{entity['id']}",
            json={"polygon": TRIANGLE},
            headers=auth,
        ).status_code == 200

    def counts():
        detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
        return {r["entity"]["id"]: r["entity"]["item_count"] for r in detail["regions"]}

    assert counts() == {room["id"]: 3, room2["id"]: 1}  # items at depths 1, 2 and 3

    # Archiving an item excludes it; archiving a container hides its subtree.
    assert client.post(
        f"{API}/entities/{item_a['id']}/archive", headers=auth
    ).status_code == 200
    assert counts()[room["id"]] == 2
    assert client.post(f"{API}/entities/{box['id']}/archive", headers=auth).status_code == 200
    assert counts()[room["id"]] == 1

    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    room_region = next(r for r in detail["regions"] if r["entity"]["id"] == room["id"])
    assert room_region["entity"]["child_count"] == 2  # direct children incl. archived


def test_floor_detail_hides_archived_room_region_until_unarchive(client, auth):
    space = _entity(client, auth, "ArchReg", "space")
    room = _entity(client, auth, "ArchRegRoom", "space", space["id"])
    floor = _floor(client, auth, space["id"], _jpeg((26, 36, 46)))
    url = f"{API}/map/floors/{floor['id']}/regions/{room['id']}"
    region_id = client.put(url, json={"polygon": TRIANGLE}, headers=auth).json()["id"]

    assert client.post(f"{API}/entities/{room['id']}/archive", headers=auth).status_code == 200
    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert detail["regions"] == []

    # The row was kept, only hidden: the trace reappears unchanged on unarchive.
    assert client.post(
        f"{API}/entities/{room['id']}/unarchive", headers=auth
    ).status_code == 200
    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert [r["id"] for r in detail["regions"]] == [region_id]


# --- placements (furniture footprints) ----------------------------------------


def test_placement_upsert_update_and_delete(client, auth):
    space = _entity(client, auth, "PlaceUp", "space")
    ward = _entity(client, auth, "PlaceUpWard", "furniture", space["id"])
    floor = _blank_floor(client, auth, space["id"])
    url = f"{API}/map/floors/{floor['id']}/placements/{ward['id']}"

    resp = _put_placement(client, auth, floor["id"], ward["id"], {"x": 10, "y": 20, "w": 300, "h": 200})
    assert resp.status_code == 200, resp.text
    placement = resp.json()
    assert set(placement.keys()) == {
        "id", "entity", "x", "y", "w", "h", "rotation", "label_x", "label_y",
    }
    assert set(placement["entity"].keys()) == {"id", "name", "child_count", "item_count"}
    assert (placement["x"], placement["y"], placement["w"], placement["h"]) == (10, 20, 300, 200)
    assert placement["rotation"] == 0
    assert placement["label_x"] is None and placement["label_y"] is None

    # Upsert: same row updated.
    resp = _put_placement(
        client, auth, floor["id"], ward["id"],
        {"x": 50, "y": 60, "w": 400, "h": 100, "label_x": 250, "label_y": 110},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == placement["id"]
    assert (updated["x"], updated["y"], updated["w"], updated["h"]) == (50, 60, 400, 100)
    assert (updated["label_x"], updated["label_y"]) == (250, 110)

    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert detail["placement_count"] == 1
    assert detail["placements"][0]["id"] == placement["id"]

    assert client.delete(url, headers=auth).status_code == 204
    assert client.delete(url, headers=auth).status_code == 404


def test_placement_validation(client, auth):
    space = _entity(client, auth, "PlaceVal", "space")
    ward = _entity(client, auth, "PlaceValWard", "furniture", space["id"])
    box = _entity(client, auth, "PlaceValBox", "container", space["id"])
    room = _entity(client, auth, "PlaceValRoom", "space", space["id"])
    other_root = _entity(client, auth, "PlaceValOther", "space")
    other_furn = _entity(client, auth, "PlaceValOtherWard", "furniture", other_root["id"])
    floor = _blank_floor(client, auth, space["id"])  # 1600x1200 canvas

    def put(entity_id, payload):
        return _put_placement(client, auth, floor["id"], entity_id, payload)

    ok = {"x": 0, "y": 0, "w": 100, "h": 100}
    # A container is placeable too.
    assert put(box["id"], ok).status_code == 200
    # Non-positive size is a schema 422.
    assert put(ward["id"], {"x": 0, "y": 0, "w": 0, "h": 100}).status_code == 422
    assert put(ward["id"], {"x": 0, "y": 0, "w": 100, "h": -5}).status_code == 422
    # Out of canvas bounds -> 409.
    assert put(ward["id"], {"x": 1550, "y": 0, "w": 100, "h": 100}).status_code == 409
    assert put(ward["id"], {"x": 0, "y": 1150, "w": 100, "h": 100}).status_code == 409
    # Kind / descendant rules -> 409.
    assert put(room["id"], ok).status_code == 409  # a space, not furniture
    assert put(space["id"], ok).status_code == 409  # the floor entity itself
    assert put(other_furn["id"], ok).status_code == 409  # not a descendant
    assert put(999999, ok).status_code == 404
    assert _put_placement(client, auth, 999999, ward["id"], ok).status_code == 404


def test_placement_finiteness_rejected_before_commit(client, auth):
    space = _entity(client, auth, "PlaceNaN", "space")
    ward = _entity(client, auth, "PlaceNaNWard", "furniture", space["id"])
    floor = _blank_floor(client, auth, space["id"])

    def put_raw(payload):
        return client.put(
            f"{API}/map/floors/{floor['id']}/placements/{ward['id']}",
            content=json.dumps(payload),
            headers={**auth, "Content-Type": "application/json"},
        )

    # NaN/inf tokens pass json.loads + pydantic floats — the SERVICE must reject,
    # else a committed non-finite would 500 every floor-detail GET.
    assert put_raw({"x": float("nan"), "y": 0, "w": 100, "h": 100}).status_code == 409
    assert put_raw({"x": 0, "y": float("inf"), "w": 100, "h": 100}).status_code == 409
    assert put_raw({"x": 0, "y": 0, "w": 100, "h": 100, "rotation": float("nan")}).status_code == 409
    assert put_raw(
        {"x": 0, "y": 0, "w": 100, "h": 100, "label_x": float("inf"), "label_y": 5}
    ).status_code == 409

    resp = client.get(f"{API}/map/floors/{floor['id']}", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["placements"] == []


def test_placement_unique_per_floor_and_item_counts(client, auth):
    space = _entity(client, auth, "PlaceCount", "space")
    ward = _entity(client, auth, "PlaceCountWard", "furniture", space["id"])
    _entity(client, auth, "PlaceCountItemA", "item", ward["id"])
    box = _entity(client, auth, "PlaceCountBox", "container", ward["id"])
    _entity(client, auth, "PlaceCountItemB", "item", box["id"])
    floor = _blank_floor(client, auth, space["id"])

    r1 = _put_placement(client, auth, floor["id"], ward["id"], {"x": 0, "y": 0, "w": 100, "h": 100})
    r2 = _put_placement(client, auth, floor["id"], ward["id"], {"x": 5, "y": 5, "w": 120, "h": 120})
    assert r1.json()["id"] == r2.json()["id"]  # UNIQUE(floor, entity): same row upserted

    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    placement = detail["placements"][0]
    assert placement["entity"]["item_count"] == 2  # items at depth 1 and 2
    assert placement["entity"]["child_count"] == 2  # direct children (item + box)


def test_placement_hidden_when_archived_until_unarchive(client, auth):
    space = _entity(client, auth, "PlaceArch", "space")
    ward = _entity(client, auth, "PlaceArchWard", "furniture", space["id"])
    floor = _blank_floor(client, auth, space["id"])
    pid = _put_placement(
        client, auth, floor["id"], ward["id"], {"x": 0, "y": 0, "w": 100, "h": 100}
    ).json()["id"]

    assert client.post(f"{API}/entities/{ward['id']}/archive", headers=auth).status_code == 200
    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert detail["placements"] == []

    assert client.post(f"{API}/entities/{ward['id']}/unarchive", headers=auth).status_code == 200
    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert [p["id"] for p in detail["placements"]] == [pid]


def test_move_furniture_out_of_floor_deletes_placement(client, auth):
    home = _entity(client, auth, "PlaceMove", "space")
    other = _entity(client, auth, "PlaceMoveOther", "space")
    den = _entity(client, auth, "PlaceMoveDen", "space", home["id"])
    ward = _entity(client, auth, "PlaceMoveWard", "furniture", home["id"])
    floor = _blank_floor(client, auth, home["id"])
    assert _put_placement(
        client, auth, floor["id"], ward["id"], {"x": 0, "y": 0, "w": 100, "h": 100}
    ).status_code == 200

    def placement_ids():
        detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
        return {p["entity"]["id"] for p in detail["placements"]}

    # WITHIN the floor subtree: still a descendant -> footprint kept.
    assert _move(client, auth, ward["id"], den["id"]).status_code == 200
    assert placement_ids() == {ward["id"]}

    # OUTSIDE: the furniture physically left this floor -> footprint deleted.
    assert _move(client, auth, ward["id"], other["id"]).status_code == 200
    assert placement_ids() == set()

    from sqlalchemy import func, select

    from app.database import get_sessionmaker
    from app.models.map import FurniturePlacement

    db = get_sessionmaker()()
    try:
        count = db.scalar(
            select(func.count(FurniturePlacement.id)).where(
                FurniturePlacement.entity_id == ward["id"]
            )
        )
    finally:
        db.close()
    assert count == 0, "placement row deleted, not just hidden"


def test_floor_delete_cascades_placements(client, auth):
    space = _entity(client, auth, "PlaceDel", "space")
    ward = _entity(client, auth, "PlaceDelWard", "furniture", space["id"])
    floor = _blank_floor(client, auth, space["id"])
    assert _put_placement(
        client, auth, floor["id"], ward["id"], {"x": 0, "y": 0, "w": 100, "h": 100}
    ).status_code == 200

    assert client.delete(f"{API}/map/floors/{floor['id']}", headers=auth).status_code == 204

    from sqlalchemy import func, select

    from app.database import get_sessionmaker
    from app.models.map import FurniturePlacement

    db = get_sessionmaker()()
    try:
        count = db.scalar(
            select(func.count(FurniturePlacement.id)).where(
                FurniturePlacement.floor_plan_id == floor["id"]
            )
        )
    finally:
        db.close()
    assert count == 0
    # The furniture entity itself survives (footprint is a view link).
    assert client.get(f"{API}/entities/{ward['id']}", headers=auth).status_code == 200


# --- grids --------------------------------------------------------------------


def test_grid_create_bulk_cells(client, auth):
    space = _entity(client, auth, "GridHome", "space")
    wardrobe = _entity(client, auth, "GridWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=3, cols=4, name="Front")

    assert set(grid.keys()) == {
        "id", "name", "rows", "cols", "parent_cell_id", "sort_order", "cells",
    }
    assert (grid["name"], grid["rows"], grid["cols"]) == ("Front", 3, 4)
    assert grid["parent_cell_id"] is None
    assert len(grid["cells"]) == 12
    assert {(c["row"], c["col"]) for c in grid["cells"]} == {
        (r, c) for r in range(3) for c in range(4)
    }
    cell = grid["cells"][0]
    assert set(cell.keys()) == {
        "id", "row", "col", "row_span", "col_span", "cell_type", "label", "entity",
    }
    assert all(c["cell_type"] == "shelf" for c in grid["cells"])
    assert all(c["row_span"] == 1 and c["col_span"] == 1 for c in grid["cells"])
    assert all(c["entity"] is None for c in grid["cells"])

    drawers = _grid(
        client, auth, entity_id=wardrobe["id"], rows=2, cols=2, default_cell_type="drawer"
    )
    assert all(c["cell_type"] == "drawer" for c in drawers["cells"])

    listed = client.get(f"{API}/map/grids", params={"entity_id": wardrobe["id"]}, headers=auth)
    assert [g["id"] for g in listed.json()] == [grid["id"], drawers["id"]]


def test_grid_create_rules(client, auth):
    space = _entity(client, auth, "GridRules", "space")
    wardrobe = _entity(client, auth, "GridRulesWardrobe", "furniture", space["id"])
    item = _entity(client, auth, "GridRulesItem", "item", space["id"])

    assert _post_grid(client, auth, entity_id=wardrobe["id"], rows=13, cols=2).status_code == 422
    assert _post_grid(client, auth, entity_id=wardrobe["id"], rows=0, cols=2).status_code == 422
    assert _post_grid(client, auth, entity_id=item["id"], rows=2, cols=2).status_code == 409
    assert _post_grid(client, auth, entity_id=space["id"], rows=2, cols=2).status_code == 409
    assert _post_grid(client, auth, entity_id=999999, rows=2, cols=2).status_code == 404
    assert _post_grid(client, auth, rows=2, cols=2).status_code == 422  # no entity, no cell
    assert _post_grid(
        client, auth, entity_id=wardrobe["id"], rows=2, cols=2, default_cell_type="cupboard"
    ).status_code == 422

    assert client.get(f"{API}/map/grids", params={"entity_id": 999999}, headers=auth).status_code == 404
    assert client.get(f"{API}/map/grids", headers=auth).status_code == 422  # entity_id required


def test_grid_resize_grow_and_shrink(client, auth):
    space = _entity(client, auth, "GridResize", "space")
    wardrobe = _entity(client, auth, "GridResizeWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=2, cols=2)
    bound = _bind(client, auth, _cell_at(grid, 0, 0)["id"], {"auto": True}).json()
    assert bound["entity"] is not None

    # Shrink to 1x1: the three unbound cells are dropped, the bound one survives.
    resp = client.patch(f"{API}/map/grids/{grid['id']}", json={"rows": 1, "cols": 1}, headers=auth)
    assert resp.status_code == 200, resp.text
    shrunk = resp.json()
    assert (shrunk["rows"], shrunk["cols"]) == (1, 1)
    assert len(shrunk["cells"]) == 1
    assert shrunk["cells"][0]["entity"]["id"] == bound["entity"]["id"]

    # Grow to 2x3: new positions filled with unbound default cells.
    resp = client.patch(f"{API}/map/grids/{grid['id']}", json={"rows": 2, "cols": 3}, headers=auth)
    assert resp.status_code == 200
    grown = resp.json()
    assert len(grown["cells"]) == 6
    assert _cell_at(grown, 0, 0)["entity"]["id"] == bound["entity"]["id"]
    fresh = [c for c in grown["cells"] if (c["row"], c["col"]) != (0, 0)]
    assert all(c["entity"] is None and c["cell_type"] == "shelf" for c in fresh)

    assert client.patch(
        f"{API}/map/grids/999999", json={"rows": 2}, headers=auth
    ).status_code == 404
    assert client.patch(
        f"{API}/map/grids/{grid['id']}", json={"rows": None}, headers=auth
    ).status_code == 422


def test_grid_shrink_dropping_bound_cell_409(client, auth):
    space = _entity(client, auth, "GridShrink", "space")
    wardrobe = _entity(client, auth, "GridShrinkWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=2, cols=2)
    assert _bind(client, auth, _cell_at(grid, 1, 1)["id"], {"auto": True}).status_code == 200

    resp = client.patch(f"{API}/map/grids/{grid['id']}", json={"rows": 1}, headers=auth)
    assert resp.status_code == 409, resp.text
    # Nothing was dropped.
    listed = client.get(
        f"{API}/map/grids", params={"entity_id": wardrobe["id"]}, headers=auth
    ).json()
    assert (listed[0]["rows"], listed[0]["cols"]) == (2, 2)
    assert len(listed[0]["cells"]) == 4


def test_grid_shrink_clamps_surviving_span_and_drops_void(client, auth):
    space = _entity(client, auth, "GridClamp", "space")
    wardrobe = _entity(client, auth, "GridClampWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=4, cols=1)

    def patch_cell(cell_id, body):
        return client.patch(f"{API}/map/cells/{cell_id}", json=body, headers=auth)

    # Row 3 becomes a hole so the row-2 cell can span over it.
    assert patch_cell(_cell_at(grid, 3, 0)["id"], {"cell_type": "void"}).status_code == 200
    spanner_id = _cell_at(grid, 2, 0)["id"]
    assert patch_cell(spanner_id, {"row_span": 2}).status_code == 200

    # Shrink to 3 rows: dropping the (unbound) VOID cell is fine, and the
    # surviving spanner's row_span is clamped back into the new bounds.
    resp = client.patch(f"{API}/map/grids/{grid['id']}", json={"rows": 3}, headers=auth)
    assert resp.status_code == 200, resp.text
    shrunk = resp.json()
    assert (shrunk["rows"], shrunk["cols"]) == (3, 1)
    assert len(shrunk["cells"]) == 3
    spanner = next(c for c in shrunk["cells"] if c["id"] == spanner_id)
    assert (spanner["row"], spanner["row_span"], spanner["col_span"]) == (2, 1, 1)


def test_grid_delete_keeps_bound_entities(client, auth):
    space = _entity(client, auth, "GridDel", "space")
    wardrobe = _entity(client, auth, "GridDelWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=2)
    bound = _bind(client, auth, _cell_at(grid, 0, 0)["id"], {"auto": True}).json()
    entity_id = bound["entity"]["id"]

    assert client.delete(f"{API}/map/grids/{grid['id']}", headers=auth).status_code == 204
    assert client.get(
        f"{API}/map/grids", params={"entity_id": wardrobe["id"]}, headers=auth
    ).json() == []
    assert client.get(f"{API}/entities/{entity_id}", headers=auth).status_code == 200
    assert client.delete(f"{API}/map/grids/{grid['id']}", headers=auth).status_code == 404


# --- cells --------------------------------------------------------------------


def test_cell_span_bounds_and_overlap(client, auth):
    space = _entity(client, auth, "CellSpan", "space")
    wardrobe = _entity(client, auth, "CellSpanWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=2, cols=2)
    top_left = _cell_at(grid, 0, 0)
    top_right = _cell_at(grid, 0, 1)
    bottom_left = _cell_at(grid, 1, 0)

    def patch(cell_id, body):
        return client.patch(f"{API}/map/cells/{cell_id}", json=body, headers=auth)

    assert patch(top_left["id"], {"row_span": 2}).status_code == 409  # overlaps (1,0)
    assert patch(top_left["id"], {"row_span": 3}).status_code == 409  # exceeds bounds
    assert patch(top_right["id"], {"col_span": 2}).status_code == 409  # exceeds bounds

    # Marking the covered cell 'void' makes it a hole the span may grow over.
    assert patch(bottom_left["id"], {"cell_type": "void"}).status_code == 200
    resp = patch(top_left["id"], {"row_span": 2})
    assert resp.status_code == 200, resp.text
    assert resp.json()["row_span"] == 2


def test_cell_patch_meta_and_errors(client, auth):
    space = _entity(client, auth, "CellPatch", "space")
    wardrobe = _entity(client, auth, "CellPatchWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=2)
    cell = _cell_at(grid, 0, 0)

    resp = client.patch(
        f"{API}/map/cells/{cell['id']}", json={"cell_type": "door", "label": "Left"}, headers=auth
    )
    assert resp.status_code == 200
    assert (resp.json()["cell_type"], resp.json()["label"]) == ("door", "Left")

    resp = client.patch(f"{API}/map/cells/{cell['id']}", json={"label": None}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["label"] is None

    assert client.patch(
        f"{API}/map/cells/{cell['id']}", json={"cell_type": None}, headers=auth
    ).status_code == 422
    assert client.patch(
        f"{API}/map/cells/{cell['id']}", json={"cell_type": "cupboard"}, headers=auth
    ).status_code == 422
    assert client.patch(
        f"{API}/map/cells/{cell['id']}", json={"row_span": 0}, headers=auth
    ).status_code == 422
    assert client.patch(f"{API}/map/cells/999999", json={}, headers=auth).status_code == 404


def test_cell_bind_auto_names_and_containment(client, auth):
    space = _entity(client, auth, "BindAuto", "space")
    wardrobe = _entity(client, auth, "BindAutoWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=2, cols=2)
    drawer_cell = _cell_at(grid, 1, 0)
    assert client.patch(
        f"{API}/map/cells/{drawer_cell['id']}", json={"cell_type": "drawer"}, headers=auth
    ).status_code == 200

    resp = _bind(client, auth, drawer_cell["id"], {"auto": True})
    assert resp.status_code == 200, resp.text
    bound = resp.json()["entity"]
    assert bound["name"] == "Drawer 2-1"  # '<CellType> <row+1>-<col+1>'
    assert (bound["child_count"], bound["item_count"]) == (0, 0)
    created = client.get(f"{API}/entities/{bound['id']}", headers=auth).json()
    assert created["kind"] == "container"
    assert created["parent_id"] == wardrobe["id"]

    # A labelled cell auto-names from the label instead.
    labelled = _cell_at(grid, 0, 1)
    assert client.patch(
        f"{API}/map/cells/{labelled['id']}", json={"label": "Left door"}, headers=auth
    ).status_code == 200
    resp = _bind(client, auth, labelled["id"], {"auto": True})
    assert resp.json()["entity"]["name"] == "Left door"

    assert _bind(
        client, auth, _cell_at(grid, 0, 0)["id"], {"auto": True, "entity_id": 5}
    ).status_code == 422


def test_cell_bind_existing_rules(client, auth):
    space = _entity(client, auth, "BindExist", "space")
    wardrobe = _entity(client, auth, "BindExistWardrobe", "furniture", space["id"])
    box = _entity(client, auth, "BindExistBox", "container", wardrobe["id"])
    item = _entity(client, auth, "BindExistItem", "item", wardrobe["id"])
    grandchild = _entity(client, auth, "BindExistInner", "container", box["id"])
    other = _entity(client, auth, "BindExistOther", "furniture", space["id"])
    other_box = _entity(client, auth, "BindExistOtherBox", "container", other["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=4)
    cell0, cell1 = _cell_at(grid, 0, 0), _cell_at(grid, 0, 1)

    resp = _bind(client, auth, cell0["id"], {"entity_id": box["id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["entity"]["id"] == box["id"]

    assert _bind(client, auth, cell1["id"], {"entity_id": item["id"]}).status_code == 409
    assert _bind(client, auth, cell1["id"], {"entity_id": grandchild["id"]}).status_code == 409
    assert _bind(client, auth, cell1["id"], {"entity_id": other_box["id"]}).status_code == 409
    # The container already renders in cell0 (UNIQUE -> 409).
    assert _bind(client, auth, cell1["id"], {"entity_id": box["id"]}).status_code == 409
    # Re-binding the same cell to the same entity is idempotent.
    assert _bind(client, auth, cell0["id"], {"entity_id": box["id"]}).status_code == 200
    assert _bind(client, auth, cell1["id"], {"entity_id": 999999}).status_code == 404


def test_bind_auto_on_bound_cell_409_explicit_rebind_allowed(client, auth):
    space = _entity(client, auth, "BindAgain", "space")
    wardrobe = _entity(client, auth, "BindAgainWardrobe", "furniture", space["id"])
    box_b = _entity(client, auth, "BindAgainBoxB", "container", wardrobe["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=1)
    cell = _cell_at(grid, 0, 0)
    assert _bind(client, auth, cell["id"], {"auto": True}).status_code == 200

    # Auto would mint ANOTHER container and silently orphan the binding.
    assert _bind(client, auth, cell["id"], {"auto": True}).status_code == 409
    # An explicit rebind is an intentional replace and stays allowed.
    resp = _bind(client, auth, cell["id"], {"entity_id": box_b["id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["entity"]["id"] == box_b["id"]


def test_bind_archived_container_409(client, auth):
    space = _entity(client, auth, "BindArch", "space")
    wardrobe = _entity(client, auth, "BindArchWardrobe", "furniture", space["id"])
    box = _entity(client, auth, "BindArchBox", "container", wardrobe["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=1)
    cell = _cell_at(grid, 0, 0)

    assert client.post(f"{API}/entities/{box['id']}/archive", headers=auth).status_code == 200
    assert _bind(client, auth, cell["id"], {"entity_id": box["id"]}).status_code == 409
    assert client.post(
        f"{API}/entities/{box['id']}/unarchive", headers=auth
    ).status_code == 200
    assert _bind(client, auth, cell["id"], {"entity_id": box["id"]}).status_code == 200


def test_archived_bound_entity_stays_visible_with_full_counts(client, auth):
    """Archiving a BOUND container: the cell keeps showing it (the physical
    drawer still holds the archived box) and the pills count include-archived —
    unlike floor-region pills, which stay archived-excluded."""
    space = _entity(client, auth, "ArchCell", "space")
    wardrobe = _entity(client, auth, "ArchCellWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=1)
    box = _bind(client, auth, _cell_at(grid, 0, 0)["id"], {"auto": True}).json()["entity"]
    _entity(client, auth, "ArchCellItem", "item", box["id"])

    assert client.post(f"{API}/entities/{box['id']}/archive", headers=auth).status_code == 200
    listed = client.get(
        f"{API}/map/grids", params={"entity_id": wardrobe["id"]}, headers=auth
    ).json()
    shown = listed[0]["cells"][0]["entity"]
    assert shown["id"] == box["id"]
    assert (shown["child_count"], shown["item_count"]) == (1, 1)


def test_void_cell_bind_rules(client, auth):
    space = _entity(client, auth, "VoidRules", "space")
    wardrobe = _entity(client, auth, "VoidRulesWardrobe", "furniture", space["id"])
    box = _entity(client, auth, "VoidRulesBox", "container", wardrobe["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=2)
    bound_cell = _cell_at(grid, 0, 0)
    void_cell = _cell_at(grid, 0, 1)
    assert _bind(client, auth, bound_cell["id"], {"auto": True}).status_code == 200

    # A bound cell cannot become a hole — unbind first.
    assert client.patch(
        f"{API}/map/cells/{bound_cell['id']}", json={"cell_type": "void"}, headers=auth
    ).status_code == 409

    # An unbound void refuses BOTH bind forms (service-side, not just the UI).
    assert client.patch(
        f"{API}/map/cells/{void_cell['id']}", json={"cell_type": "void"}, headers=auth
    ).status_code == 200
    assert _bind(client, auth, void_cell["id"], {"auto": True}).status_code == 409
    assert _bind(client, auth, void_cell["id"], {"entity_id": box["id"]}).status_code == 409
    # Unbinding a void stays a harmless no-op.
    assert _bind(client, auth, void_cell["id"], {"entity_id": None}).status_code == 200


def test_cell_unbind_leaves_entity(client, auth):
    space = _entity(client, auth, "Unbind", "space")
    wardrobe = _entity(client, auth, "UnbindWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=1)
    cell = _cell_at(grid, 0, 0)
    bound = _bind(client, auth, cell["id"], {"auto": True}).json()

    resp = _bind(client, auth, cell["id"], {"entity_id": None})
    assert resp.status_code == 200
    assert resp.json()["entity"] is None
    assert client.get(f"{API}/entities/{bound['entity']['id']}", headers=auth).status_code == 200
    # Unbinding an unbound cell is a no-op.
    assert _bind(client, auth, cell["id"], {"entity_id": None}).status_code == 200


# --- sub-grids ----------------------------------------------------------------


def test_subgrid_rules_and_cascade(client, auth):
    space = _entity(client, auth, "SubGrid", "space")
    wardrobe = _entity(client, auth, "SubGridWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=2, cols=2)
    cell = _cell_at(grid, 0, 0)

    # The anchor cell must be bound first.
    assert _post_grid(client, auth, parent_cell_id=cell["id"], rows=1, cols=2).status_code == 409
    assert _post_grid(client, auth, parent_cell_id=999999, rows=1, cols=2).status_code == 404

    bound = _bind(client, auth, cell["id"], {"auto": True}).json()
    inner_entity = bound["entity"]["id"]

    sub = _grid(client, auth, parent_cell_id=cell["id"], rows=1, cols=2, name="Inside")
    assert sub["parent_cell_id"] == cell["id"]
    # entity_id was auto-set to the cell's bound entity: the sub-grid renders it.
    listed = client.get(
        f"{API}/map/grids", params={"entity_id": inner_entity}, headers=auth
    ).json()
    assert [g["id"] for g in listed] == [sub["id"]]

    # An explicit mismatching entity_id is refused.
    assert _post_grid(
        client, auth, parent_cell_id=cell["id"], entity_id=wardrobe["id"], rows=1, cols=1
    ).status_code == 409
    # The anchor binding is frozen while the sub-grid exists.
    assert _bind(client, auth, cell["id"], {"entity_id": None}).status_code == 409
    assert _bind(client, auth, cell["id"], {"auto": True}).status_code == 409

    # Deleting the parent grid cascades through its cells to the sub-grid...
    assert client.delete(f"{API}/map/grids/{grid['id']}", headers=auth).status_code == 204
    assert client.get(
        f"{API}/map/grids", params={"entity_id": inner_entity}, headers=auth
    ).json() == []
    # ...but the bound entity survives (bindings are view links).
    assert client.get(f"{API}/entities/{inner_entity}", headers=auth).status_code == 200


# --- entity move interactions (view-layer consistency) -------------------------


def _move(client, auth, entity_id, parent_id):
    return client.post(
        f"{API}/entities/{entity_id}/move", json={"parent_id": parent_id}, headers=auth
    )


def test_move_bound_container_unbinds_cell_and_detaches_subgrid(client, auth):
    space = _entity(client, auth, "MoveBind", "space")
    wardrobe = _entity(client, auth, "MoveBindWardrobe", "furniture", space["id"])
    dresser = _entity(client, auth, "MoveBindDresser", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=2)
    cell = _cell_at(grid, 0, 0)
    box_id = _bind(client, auth, cell["id"], {"auto": True}).json()["entity"]["id"]
    sub = _grid(client, auth, parent_cell_id=cell["id"], rows=1, cols=2, name="Inside")

    # The box physically moves into the dresser: the wardrobe's cell no longer
    # holds it (the drawer stays; the box moved elsewhere) -> unbound. The
    # inner layout belongs to the BOX and survives detached as its own
    # top-level grid, still viewable from the box's Layout section.
    assert _move(client, auth, box_id, dresser["id"]).status_code == 200
    listed = client.get(
        f"{API}/map/grids", params={"entity_id": wardrobe["id"]}, headers=auth
    ).json()
    assert _cell_at(listed[0], 0, 0)["entity"] is None
    inner = client.get(
        f"{API}/map/grids", params={"entity_id": box_id}, headers=auth
    ).json()
    assert [g["id"] for g in inner] == [sub["id"]]
    assert inner[0]["parent_cell_id"] is None


def test_move_parent_furniture_keeps_descendant_bindings(client, auth):
    space = _entity(client, auth, "MoveKeep", "space")
    den = _entity(client, auth, "MoveKeepDen", "space", space["id"])
    wardrobe = _entity(client, auth, "MoveKeepWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=1)
    box_id = _bind(client, auth, _cell_at(grid, 0, 0)["id"], {"auto": True}).json()[
        "entity"
    ]["id"]

    # The wardrobe moves with everything in it: its cells' bindings are
    # RELATIVE (the box is still the wardrobe's direct child) and stay valid.
    assert _move(client, auth, wardrobe["id"], den["id"]).status_code == 200
    listed = client.get(
        f"{API}/map/grids", params={"entity_id": wardrobe["id"]}, headers=auth
    ).json()
    assert listed[0]["cells"][0]["entity"]["id"] == box_id


def test_move_room_regions_follow_floor_subtree(client, auth):
    home = _entity(client, auth, "MoveReg", "space")
    other = _entity(client, auth, "MoveRegOther", "space")
    room = _entity(client, auth, "MoveRegRoom", "space", home["id"])
    hall = _entity(client, auth, "MoveRegHall", "space", home["id"])
    floor = _floor(client, auth, home["id"], _jpeg((25, 35, 45)))
    for entity in (room, hall):
        assert client.put(
            f"{API}/map/floors/{floor['id']}/regions/{entity['id']}",
            json={"polygon": TRIANGLE},
            headers=auth,
        ).status_code == 200

    def region_ids():
        detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
        return {r["entity"]["id"] for r in detail["regions"]}

    # WITHIN the floor's subtree: still a descendant -> the region is kept.
    assert _move(client, auth, room["id"], hall["id"]).status_code == 200
    assert region_ids() == {room["id"], hall["id"]}

    # OUTSIDE: the room physically left this floor -> its region row is deleted.
    assert _move(client, auth, room["id"], other["id"]).status_code == 200
    assert region_ids() == {hall["id"]}

    from sqlalchemy import func, select

    from app.database import get_sessionmaker
    from app.models.map import MapRegion

    db = get_sessionmaker()()
    try:
        count = db.scalar(
            select(func.count(MapRegion.id)).where(MapRegion.entity_id == room["id"])
        )
    finally:
        db.close()
    assert count == 0, "region row deleted, not just hidden"


# --- entity delete interactions -----------------------------------------------


def test_entity_delete_sets_cell_binding_null(client, auth):
    space = _entity(client, auth, "EntDelCell", "space")
    wardrobe = _entity(client, auth, "EntDelCellWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=1)
    bound = _bind(client, auth, _cell_at(grid, 0, 0)["id"], {"auto": True}).json()

    assert client.delete(
        f"{API}/entities/{bound['entity']['id']}", headers=auth
    ).status_code == 204
    listed = client.get(
        f"{API}/map/grids", params={"entity_id": wardrobe["id"]}, headers=auth
    ).json()
    assert listed[0]["cells"][0]["entity"] is None  # FK SET NULL


def test_entity_delete_cascades_anchored_subgrid(client, auth):
    space = _entity(client, auth, "EntDelSub", "space")
    wardrobe = _entity(client, auth, "EntDelSubWardrobe", "furniture", space["id"])
    grid = _grid(client, auth, entity_id=wardrobe["id"], rows=1, cols=1)
    cell = _cell_at(grid, 0, 0)
    box_id = _bind(client, auth, cell["id"], {"auto": True}).json()["entity"]["id"]
    sub = _grid(client, auth, parent_cell_id=cell["id"], rows=1, cols=2)

    # Deleting the bound container: the anchor cell goes SET NULL, while the
    # sub-grid (it rendered the deleted entity) cascades away with its cells.
    assert client.delete(f"{API}/entities/{box_id}", headers=auth).status_code == 204
    listed = client.get(
        f"{API}/map/grids", params={"entity_id": wardrobe["id"]}, headers=auth
    ).json()
    assert [g["id"] for g in listed] == [grid["id"]]
    assert listed[0]["cells"][0]["entity"] is None

    from sqlalchemy import func, select

    from app.database import get_sessionmaker
    from app.models.map import FurnitureGrid, GridCell

    db = get_sessionmaker()()
    try:
        sub_rows = db.scalar(
            select(func.count(FurnitureGrid.id)).where(FurnitureGrid.id == sub["id"])
        )
        sub_cells = db.scalar(
            select(func.count(GridCell.id)).where(GridCell.grid_id == sub["id"])
        )
    finally:
        db.close()
    assert (sub_rows, sub_cells) == (0, 0)


def test_entity_delete_cascades_floor_and_regions(client, auth):
    space = _entity(client, auth, "EntDelFloor", "space")
    room = _entity(client, auth, "EntDelFloorRoom", "space", space["id"])
    floor = _floor(client, auth, space["id"], _jpeg((21, 31, 41)))
    assert client.put(
        f"{API}/map/floors/{floor['id']}/regions/{room['id']}",
        json={"polygon": TRIANGLE},
        headers=auth,
    ).status_code == 200

    # Deleting the traced room removes its region; the floor survives.
    assert client.delete(f"{API}/entities/{room['id']}", headers=auth).status_code == 204
    detail = client.get(f"{API}/map/floors/{floor['id']}", headers=auth).json()
    assert detail["regions"] == []
    assert detail["entity"]["id"] == space["id"]

    # Deleting a childless space with a plan cascades the plan and cleans the file.
    lone = _entity(client, auth, "EntDelFloorLone", "space")
    lone_floor = _floor(client, auth, lone["id"], _jpeg((22, 32, 42)))
    disk = _disk_path(lone_floor["image_url"])
    assert disk.exists()
    assert client.delete(f"{API}/entities/{lone['id']}", headers=auth).status_code == 204
    assert lone_floor["id"] not in [
        f["id"] for f in client.get(f"{API}/map/floors", headers=auth).json()
    ]
    assert not disk.exists(), "entity delete runs the refcounted floor-image cleanup"


# --- /media serving -----------------------------------------------------------


def test_floorplan_media_traversal_and_404(client, auth):
    space = _entity(client, auth, "MediaGuard", "space")
    floor = _floor(client, auth, space["id"], _jpeg((23, 33, 43)))
    resp = client.get(floor["image_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"

    assert (_data_dir() / "secret.key").is_file()
    assert client.get("/media/floorplans/%2e%2e/secret.key").status_code == 404
    resp = client.get("/media/floorplans/zz/nope.jpg")
    assert resp.status_code == 404
    assert "text/html" not in resp.headers.get("content-type", "")
