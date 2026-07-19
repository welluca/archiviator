"""Entity tree tests: containment matrix, cache maintenance, moves, archive, Inbox."""

import pytest

API = "/api/v1/entities"


@pytest.fixture(scope="module")
def auth(client, test_user):
    """One login for the whole module (same pattern as the tokens fixture)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create(client, auth, name, kind, parent_id=None, **extra):
    payload = {"name": name, "kind": kind, "parent_id": parent_id, **extra}
    return client.post(API, json=payload, headers=auth)


def _make(client, auth, name, kind, parent_id=None, **extra):
    resp = _create(client, auth, name, kind, parent_id, **extra)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _get(client, auth, entity_id):
    resp = client.get(f"{API}/{entity_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- auth & shape -------------------------------------------------------------


def test_requires_auth(client):
    assert client.get(f"{API}/tree").status_code == 401


def test_entity_out_shape(client, auth):
    e = _make(client, auth, "ShapeTest", "space")
    assert set(e.keys()) == {
        "id", "kind", "subtype", "name", "description", "notes", "parent_id",
        "depth", "breadcrumb", "asset_tag", "draft", "archived", "protected",
        "child_count", "cover_attachment_id", "thumb_url", "created_at", "updated_at",
    }
    assert e["kind"] == "space"
    assert e["parent_id"] is None
    assert e["depth"] == 0
    assert e["breadcrumb"] == "ShapeTest"
    assert e["archived"] is False
    assert e["draft"] is False
    assert e["child_count"] == 0
    assert e["cover_attachment_id"] is None
    assert e["thumb_url"] is None


# --- containment matrix -------------------------------------------------------

MATRIX = [
    ("space", "space", True),
    ("space", "furniture", True),
    ("space", "container", True),
    ("space", "item", True),
    ("furniture", "space", False),
    ("furniture", "furniture", False),
    ("furniture", "container", True),
    ("furniture", "item", True),
    ("container", "space", False),
    ("container", "furniture", False),
    ("container", "container", True),
    ("container", "item", True),
    ("item", "space", False),
    ("item", "furniture", False),
    ("item", "container", False),
    ("item", "item", False),
]


@pytest.mark.parametrize("parent_kind,child_kind,allowed", MATRIX)
def test_containment_matrix(client, auth, parent_kind, child_kind, allowed):
    root = _make(client, auth, "MatrixRoot", "space")
    parent = root if parent_kind == "space" else _make(
        client, auth, f"P-{parent_kind}", parent_kind, root["id"]
    )
    resp = _create(client, auth, f"C-{child_kind}", child_kind, parent["id"])
    if allowed:
        assert resp.status_code == 201, resp.text
    else:
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]


@pytest.mark.parametrize("kind", ["furniture", "container", "item"])
def test_root_must_be_space(client, auth, kind):
    resp = _create(client, auth, "Rootless", kind, None)
    assert resp.status_code == 409


def test_multiple_root_spaces_allowed(client, auth):
    a = _make(client, auth, "RootA", "space")
    b = _make(client, auth, "RootB", "space")
    assert a["id"] != b["id"]
    assert a["parent_id"] is None and b["parent_id"] is None


# --- cache computation --------------------------------------------------------


def test_create_computes_caches_at_depth(client, auth):
    a = _make(client, auth, "Attic", "space")
    b = _make(client, auth, "Wardrobe", "furniture", a["id"])
    c = _make(client, auth, "Shoe Box", "container", b["id"])
    d = _make(client, auth, "Left Shoe", "item", c["id"])

    assert (a["depth"], a["breadcrumb"]) == (0, "Attic")
    assert (b["depth"], b["breadcrumb"]) == (1, "Attic › Wardrobe")
    assert (c["depth"], c["breadcrumb"]) == (2, "Attic › Wardrobe › Shoe Box")
    assert (d["depth"], d["breadcrumb"]) == (3, "Attic › Wardrobe › Shoe Box › Left Shoe")
    assert d["parent_id"] == c["id"]

    path = client.get(f"{API}/{d['id']}/path", headers=auth).json()
    assert [(p["id"], p["kind"]) for p in path] == [
        (a["id"], "space"), (b["id"], "furniture"), (c["id"], "container"), (d["id"], "item"),
    ]


def test_path_endpoint_root_first_including_self(client, auth):
    a = _make(client, auth, "PRoot", "space")
    b = _make(client, auth, "PMid", "furniture", a["id"])
    c = _make(client, auth, "PLeaf", "item", b["id"])
    path = client.get(f"{API}/{c['id']}/path", headers=auth).json()
    assert path == [
        {"id": a["id"], "name": "PRoot", "kind": "space"},
        {"id": b["id"], "name": "PMid", "kind": "furniture"},
        {"id": c["id"], "name": "PLeaf", "kind": "item"},
    ]
    # A root's path is just itself.
    assert client.get(f"{API}/{a['id']}/path", headers=auth).json() == [
        {"id": a["id"], "name": "PRoot", "kind": "space"}
    ]


def test_tree_ordered_parents_before_children(client, auth):
    root = _make(client, auth, "TreeOrder", "space")
    kid = _make(client, auth, "TreeKid", "container", root["id"])
    grand = _make(client, auth, "TreeGrand", "item", kid["id"])
    rows = client.get(f"{API}/tree", headers=auth).json()
    pos = {e["id"]: i for i, e in enumerate(rows)}
    assert pos[root["id"]] < pos[kid["id"]] < pos[grand["id"]]
    for e in rows:
        if e["parent_id"] is not None and e["parent_id"] in pos:
            assert pos[e["parent_id"]] < pos[e["id"]]


# --- rename -------------------------------------------------------------------


def test_rename_rewrites_subtree_breadcrumbs_sibling_untouched(client, auth):
    root = _make(client, auth, "Garage", "space")
    shelf = _make(client, auth, "Shelf", "furniture", root["id"])
    box = _make(client, auth, "Box", "container", shelf["id"])
    part = _make(client, auth, "Part", "item", box["id"])
    sibling = _make(client, auth, "Bench", "furniture", root["id"])

    resp = client.patch(f"{API}/{shelf['id']}", json={"name": "Rack"}, headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Rack"
    assert resp.json()["breadcrumb"] == "Garage › Rack"

    assert _get(client, auth, box["id"])["breadcrumb"] == "Garage › Rack › Box"
    assert _get(client, auth, part["id"])["breadcrumb"] == "Garage › Rack › Box › Part"
    assert _get(client, auth, sibling["id"])["breadcrumb"] == "Garage › Bench"
    assert _get(client, auth, root["id"])["breadcrumb"] == "Garage"


def test_rename_ancestor_with_same_named_descendant(client, auth):
    # A descendant named exactly like the renamed ancestor must NOT be rewritten.
    outer = _make(client, auth, "Bin", "space")
    inner = _make(client, auth, "Bin", "container", outer["id"])
    thing = _make(client, auth, "Bin", "item", inner["id"])

    resp = client.patch(f"{API}/{outer['id']}", json={"name": "Crate"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["breadcrumb"] == "Crate"
    assert _get(client, auth, inner["id"])["breadcrumb"] == "Crate › Bin"
    assert _get(client, auth, thing["id"])["breadcrumb"] == "Crate › Bin › Bin"


def test_patch_other_fields(client, auth):
    e = _make(client, auth, "PatchMe", "container", _make(client, auth, "PatchRoot", "space")["id"])
    resp = client.patch(
        f"{API}/{e['id']}",
        json={"subtype": "drawer", "description": "top drawer", "notes": "squeaky"},
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["subtype"] == "drawer"
    assert body["description"] == "top drawer"
    assert body["notes"] == "squeaky"
    assert body["name"] == "PatchMe"  # unchanged


# --- move ---------------------------------------------------------------------


def test_move_rewrites_whole_subtree(client, auth):
    a = _make(client, auth, "House", "space")
    b = _make(client, auth, "Cellar", "space", a["id"])
    f = _make(client, auth, "Cabinet", "furniture", a["id"])
    c = _make(client, auth, "CBin", "container", f["id"])
    i = _make(client, auth, "Widget", "item", c["id"])
    sibling = _make(client, auth, "Sofa", "furniture", a["id"])

    resp = client.post(f"{API}/{f['id']}/move", json={"parent_id": b["id"]}, headers=auth)
    assert resp.status_code == 200, resp.text
    moved = resp.json()
    assert moved["parent_id"] == b["id"]
    assert moved["depth"] == 2
    assert moved["breadcrumb"] == "House › Cellar › Cabinet"

    c2 = _get(client, auth, c["id"])
    i2 = _get(client, auth, i["id"])
    assert (c2["depth"], c2["breadcrumb"]) == (3, "House › Cellar › Cabinet › CBin")
    assert (i2["depth"], i2["breadcrumb"]) == (4, "House › Cellar › Cabinet › CBin › Widget")

    # Grandchild's /path is consistent with the new location (path cache rewritten).
    path = client.get(f"{API}/{i['id']}/path", headers=auth).json()
    assert [p["name"] for p in path] == ["House", "Cellar", "Cabinet", "CBin", "Widget"]

    # Sibling left behind is untouched.
    sib = _get(client, auth, sibling["id"])
    assert (sib["depth"], sib["breadcrumb"]) == (1, "House › Sofa")


def test_move_space_to_root_and_back(client, auth):
    a = _make(client, auth, "Homeland", "space")
    b = _make(client, auth, "Annex", "space", a["id"])
    resp = client.post(f"{API}/{b['id']}/move", json={"parent_id": None}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["parent_id"] is None
    assert resp.json()["depth"] == 0
    assert resp.json()["breadcrumb"] == "Annex"
    resp = client.post(f"{API}/{b['id']}/move", json={"parent_id": a["id"]}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["breadcrumb"] == "Homeland › Annex"


def test_move_non_space_to_root_rejected(client, auth):
    root = _make(client, auth, "MoveRootRules", "space")
    f = _make(client, auth, "Dresser", "furniture", root["id"])
    resp = client.post(f"{API}/{f['id']}/move", json={"parent_id": None}, headers=auth)
    assert resp.status_code == 409


def test_move_cycle_guard(client, auth):
    a = _make(client, auth, "CycleRoot", "space")
    b = _make(client, auth, "CycleMid", "space", a["id"])
    c = _make(client, auth, "CycleLeaf", "space", b["id"])
    # Into itself, into own child, into own grandchild — all 409.
    for target in (a["id"], b["id"], c["id"]):
        resp = client.post(f"{API}/{a['id']}/move", json={"parent_id": target}, headers=auth)
        assert resp.status_code == 409, f"expected 409 moving under {target}"


def test_move_item_into_item_rejected(client, auth):
    root = _make(client, auth, "MoveMatrix", "space")
    i1 = _make(client, auth, "Bolt", "item", root["id"])
    i2 = _make(client, auth, "Nut", "item", root["id"])
    resp = client.post(f"{API}/{i1['id']}/move", json={"parent_id": i2["id"]}, headers=auth)
    assert resp.status_code == 409


def test_move_furniture_into_furniture_rejected(client, auth):
    root = _make(client, auth, "MoveMatrix2", "space")
    f1 = _make(client, auth, "Table", "furniture", root["id"])
    f2 = _make(client, auth, "Chair", "furniture", root["id"])
    resp = client.post(f"{API}/{f1['id']}/move", json={"parent_id": f2["id"]}, headers=auth)
    assert resp.status_code == 409


# --- delete -------------------------------------------------------------------


def test_delete_with_children_rejected(client, auth):
    root = _make(client, auth, "DelRoot", "space")
    _make(client, auth, "DelChild", "container", root["id"])
    resp = client.delete(f"{API}/{root['id']}", headers=auth)
    assert resp.status_code == 409


def test_delete_with_archived_child_still_rejected(client, auth):
    root = _make(client, auth, "DelRoot2", "space")
    child = _make(client, auth, "DelChild2", "container", root["id"])
    assert client.post(f"{API}/{child['id']}/archive", headers=auth).status_code == 200
    resp = client.delete(f"{API}/{root['id']}", headers=auth)
    assert resp.status_code == 409


def test_delete_childless_204_then_404(client, auth):
    root = _make(client, auth, "DelRoot3", "space")
    child = _make(client, auth, "DelChild3", "item", root["id"])
    resp = client.delete(f"{API}/{child['id']}", headers=auth)
    assert resp.status_code == 204
    assert client.get(f"{API}/{child['id']}", headers=auth).status_code == 404
    # Parent is now childless and deletable too.
    assert client.delete(f"{API}/{root['id']}", headers=auth).status_code == 204


# --- archive ------------------------------------------------------------------


def test_archive_hides_from_default_listings(client, auth):
    root = _make(client, auth, "ArchSpace", "space")
    box = _make(client, auth, "ArchBox", "container", root["id"])

    resp = client.post(f"{API}/{box['id']}/archive", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["archived"] is True

    tree_ids = [e["id"] for e in client.get(f"{API}/tree", headers=auth).json()]
    assert box["id"] not in tree_ids
    tree_all = [
        e["id"]
        for e in client.get(f"{API}/tree", params={"include_archived": "true"}, headers=auth).json()
    ]
    assert box["id"] in tree_all

    kids = client.get(f"{API}/{root['id']}/children", headers=auth).json()
    assert box["id"] not in [k["id"] for k in kids]
    kids_all = client.get(
        f"{API}/{root['id']}/children", params={"include_archived": "true"}, headers=auth
    ).json()
    assert box["id"] in [k["id"] for k in kids_all]

    # child_count counts archived children too (they still exist, like for delete).
    assert _get(client, auth, root["id"])["child_count"] == 1

    resp = client.post(f"{API}/{box['id']}/unarchive", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["archived"] is False
    assert box["id"] in [e["id"] for e in client.get(f"{API}/tree", headers=auth).json()]


# --- inbox --------------------------------------------------------------------


def _inbox(client, auth):
    rows = client.get(f"{API}/tree", headers=auth).json()
    return next(e for e in rows if e["protected"])


def test_inbox_seeded(client, auth):
    inbox = _inbox(client, auth)
    assert inbox["parent_id"] is None
    assert inbox["depth"] == 0


def test_inbox_cannot_be_moved_or_deleted_but_renames(client, auth):
    inbox = _inbox(client, auth)
    other = _make(client, auth, "InboxTarget", "space")

    resp = client.post(f"{API}/{inbox['id']}/move", json={"parent_id": other["id"]}, headers=auth)
    assert resp.status_code == 409
    resp = client.post(f"{API}/{inbox['id']}/move", json={"parent_id": None}, headers=auth)
    assert resp.status_code == 409
    assert client.delete(f"{API}/{inbox['id']}", headers=auth).status_code == 409

    resp = client.patch(f"{API}/{inbox['id']}", json={"name": "Inbox Renamed"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Inbox Renamed"
    assert resp.json()["breadcrumb"] == "Inbox Renamed"
    # Restore for other tests.
    resp = client.patch(f"{API}/{inbox['id']}", json={"name": "Inbox"}, headers=auth)
    assert resp.status_code == 200


# --- listings -----------------------------------------------------------------


def test_child_count_correct(client, auth):
    root = _make(client, auth, "CountRoot", "space")
    _make(client, auth, "CK1", "container", root["id"])
    k2 = _make(client, auth, "CK2", "container", root["id"])
    _make(client, auth, "CG1", "item", k2["id"])

    assert _get(client, auth, root["id"])["child_count"] == 2

    tree_row = next(
        e for e in client.get(f"{API}/tree", headers=auth).json() if e["id"] == root["id"]
    )
    assert tree_row["child_count"] == 2

    children = client.get(f"{API}/{root['id']}/children", headers=auth).json()
    by_id = {c["id"]: c for c in children}
    assert by_id[k2["id"]]["child_count"] == 1


def test_children_ordering_non_items_first_then_names(client, auth):
    root = _make(client, auth, "OrderRoot", "space")
    _make(client, auth, "Zebra Box", "container", root["id"])
    _make(client, auth, "Apple", "item", root["id"])
    _make(client, auth, "Desk", "furniture", root["id"])
    _make(client, auth, "Annex", "space", root["id"])
    names = [c["name"] for c in client.get(f"{API}/{root['id']}/children", headers=auth).json()]
    assert names == ["Annex", "Desk", "Zebra Box", "Apple"]


# --- 404s ---------------------------------------------------------------------


def test_unknown_ids_404(client, auth):
    missing = 999999
    assert client.get(f"{API}/{missing}", headers=auth).status_code == 404
    assert client.get(f"{API}/{missing}/children", headers=auth).status_code == 404
    assert client.get(f"{API}/{missing}/path", headers=auth).status_code == 404
    assert client.patch(f"{API}/{missing}", json={"name": "X"}, headers=auth).status_code == 404
    assert (
        client.post(f"{API}/{missing}/move", json={"parent_id": None}, headers=auth).status_code
        == 404
    )
    assert client.post(f"{API}/{missing}/archive", headers=auth).status_code == 404
    assert client.post(f"{API}/{missing}/unarchive", headers=auth).status_code == 404
    assert client.delete(f"{API}/{missing}", headers=auth).status_code == 404
    assert _create(client, auth, "Orphan", "space", missing).status_code == 404


def test_move_to_unknown_parent_404(client, auth):
    root = _make(client, auth, "Move404", "space")
    resp = client.post(f"{API}/{root['id']}/move", json={"parent_id": 999999}, headers=auth)
    assert resp.status_code == 404


# --- M2 hardening (adversarial-review regressions) ----------------------------


def test_inbox_is_flagged_protected(client, auth):
    assert _inbox(client, auth)["protected"] is True
    other = _make(client, auth, "NotProtected", "space")
    assert other["protected"] is False


def test_inbox_protection_survives_subtype_patch(client, auth):
    """Protection is keyed to the seeded row's id, not the mutable subtype."""
    inbox = _inbox(client, auth)
    assert client.patch(
        f"{API}/{inbox['id']}", json={"subtype": None}, headers=auth
    ).status_code == 200
    try:
        assert client.delete(f"{API}/{inbox['id']}", headers=auth).status_code == 409
        assert client.post(f"{API}/{inbox['id']}/archive", headers=auth).status_code == 409
        assert client.post(
            f"{API}/{inbox['id']}/move", json={"parent_id": None}, headers=auth
        ).status_code == 409
    finally:
        client.patch(f"{API}/{inbox['id']}", json={"subtype": "inbox"}, headers=auth)


def test_fake_inbox_root_is_not_protected(client, auth):
    fake = _make(client, auth, "Fake Inbox", "space", subtype="inbox")
    assert fake["protected"] is False
    assert client.post(f"{API}/{fake['id']}/archive", headers=auth).status_code == 200
    assert client.post(f"{API}/{fake['id']}/unarchive", headers=auth).status_code == 200
    assert client.delete(f"{API}/{fake['id']}", headers=auth).status_code == 204


def test_blank_names_rejected_and_trimmed(client, auth):
    assert _create(client, auth, "   ", "space").status_code == 422
    root = _make(client, auth, "  Trimmed Name  ", "space")
    assert root["name"] == "Trimmed Name"
    assert (
        client.patch(f"{API}/{root['id']}", json={"name": " "}, headers=auth).status_code
        == 422
    )


def test_tree_hides_whole_archived_subtree(client, auth):
    root = _make(client, auth, "ArcSub", "space")
    box = _make(client, auth, "ArcBox", "container", root["id"])
    item = _make(client, auth, "ArcItem", "item", box["id"])
    client.post(f"{API}/{box['id']}/archive", headers=auth)

    ids = {e["id"] for e in client.get(f"{API}/tree", headers=auth).json()}
    assert root["id"] in ids
    assert box["id"] not in ids
    assert item["id"] not in ids  # live item inside an archived box hides with it

    ids = {
        e["id"]
        for e in client.get(f"{API}/tree?include_archived=true", headers=auth).json()
    }
    assert box["id"] in ids and item["id"] in ids


def test_noop_move_keeps_caches(client, auth):
    root = _make(client, auth, "NoopRoot", "space")
    box = _make(client, auth, "NoopBox", "container", root["id"])
    before = _get(client, auth, box["id"])
    assert (
        client.post(
            f"{API}/{box['id']}/move", json={"parent_id": root["id"]}, headers=auth
        ).status_code
        == 200
    )
    after = _get(client, auth, box["id"])
    assert (after["breadcrumb"], after["depth"], after["parent_id"]) == (
        before["breadcrumb"],
        before["depth"],
        before["parent_id"],
    )


def test_move_under_archived_parent_allowed_but_hidden(client, auth):
    target = _make(client, auth, "ArcTarget", "space")
    client.post(f"{API}/{target['id']}/archive", headers=auth)
    loose = _make(client, auth, "LooseSpace", "space")
    resp = client.post(
        f"{API}/{loose['id']}/move", json={"parent_id": target["id"]}, headers=auth
    )
    assert resp.status_code == 200
    ids = {e["id"] for e in client.get(f"{API}/tree", headers=auth).json()}
    assert loose["id"] not in ids


def test_rename_with_substring_descendant_breadcrumbs(client, auth):
    """Rename 'Box' -> 'Crate' must not corrupt descendant 'Toolbox' or sibling 'Boxer'."""
    root = _make(client, auth, "Box", "space")
    child = _make(client, auth, "Toolbox", "container", root["id"])
    sib = _make(client, auth, "Boxer", "space")

    assert (
        client.patch(f"{API}/{root['id']}", json={"name": "Crate"}, headers=auth).status_code
        == 200
    )
    assert _get(client, auth, child["id"])["breadcrumb"] == "Crate › Toolbox"
    assert _get(client, auth, sib["id"])["breadcrumb"] == "Boxer"


def test_path_prefix_collision_between_ids(client, auth):
    """Rows whose id strings share a prefix ('/9001/' vs '/90010/') must not be
    touched by each other's subtree rewrites — a regression to LIKE 'prefix%'
    (without the trailing slash) or naive REPLACE would corrupt the decoys."""
    from app.database import get_sessionmaker
    from app.models.entity import Entity as E

    with get_sessionmaker()() as db:
        db.add_all(
            [
                E(id=9001, kind="space", name="ColA", path="/9001/", depth=0, breadcrumb="ColA"),
                E(
                    id=9002, kind="container", name="ColABox", parent_id=9001,
                    path="/9001/9002/", depth=1, breadcrumb="ColA › ColABox",
                ),
                E(id=90010, kind="space", name="Decoy", path="/90010/", depth=0, breadcrumb="Decoy"),
                E(
                    id=90011, kind="item", name="DecoyItem", parent_id=90010,
                    path="/90010/90011/", depth=1, breadcrumb="Decoy › DecoyItem",
                ),
            ]
        )
        db.commit()

    assert (
        client.patch(f"{API}/9001", json={"name": "ColRenamed"}, headers=auth).status_code
        == 200
    )
    new_home = _make(client, auth, "ColNewHome", "space")
    assert (
        client.post(
            f"{API}/9001/move", json={"parent_id": new_home["id"]}, headers=auth
        ).status_code
        == 200
    )

    # Decoys untouched by both rewrites…
    assert _get(client, auth, 90010)["breadcrumb"] == "Decoy"
    decoy_item = _get(client, auth, 90011)
    assert decoy_item["breadcrumb"] == "Decoy › DecoyItem"
    assert decoy_item["parent_id"] == 90010
    assert decoy_item["depth"] == 1
    # …while the real subtree did rewrite all the way down.
    assert _get(client, auth, 9002)["breadcrumb"] == "ColNewHome › ColRenamed › ColABox"
    assert _get(client, auth, 9002)["depth"] == 2
