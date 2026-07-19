"""M4 metadata tests: tags, categories, custom fields, presets, duplication."""

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


def _entity(client, auth, name, kind="space", parent_id=None):
    resp = client.post(
        f"{API}/entities",
        json={"name": name, "kind": kind, "parent_id": parent_id},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _get_entity(client, auth, entity_id):
    resp = client.get(f"{API}/entities/{entity_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _put_tags(client, auth, entity_id, names):
    resp = client.put(f"{API}/entities/{entity_id}/tags", json={"tags": names}, headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _category(client, auth, name, **extra):
    resp = client.post(f"{API}/categories", json={"name": name, **extra}, headers=auth)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _field(client, auth, name, type, category_id=None, **extra):
    payload = {"name": name, "type": type, "category_id": category_id, **extra}
    resp = client.post(f"{API}/fields", json=payload, headers=auth)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _put_fields(client, auth, entity_id, values):
    return client.put(
        f"{API}/entities/{entity_id}/fields", json={"values": values}, headers=auth
    )


def _tag_by_name(client, auth, name):
    rows = client.get(f"{API}/tags", headers=auth).json()
    return next((t for t in rows if t["name"].lower() == name.lower()), None)


def _jpeg(size=(64, 48), color=(90, 10, 10)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


# --- tags ---------------------------------------------------------------------


def test_tags_require_auth(client):
    assert client.get(f"{API}/tags").status_code == 401


def test_tag_crud_and_nocase_duplicate(client, auth):
    resp = client.post(f"{API}/tags", json={"name": "Vintage", "color": "#a00"}, headers=auth)
    assert resp.status_code == 201, resp.text
    tag = resp.json()
    assert set(tag.keys()) == {"id", "name", "color", "usage_count"}
    assert tag["name"] == "Vintage"
    assert tag["color"] == "#a00"
    assert tag["usage_count"] == 0

    # NOCASE duplicate rejected.
    assert client.post(f"{API}/tags", json={"name": "vintage"}, headers=auth).status_code == 409
    assert client.post(f"{API}/tags", json={"name": "VINTAGE "}, headers=auth).status_code == 409

    resp = client.patch(f"{API}/tags/{tag['id']}", json={"color": "#0a0"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["color"] == "#0a0"
    assert resp.json()["name"] == "Vintage"

    resp = client.patch(f"{API}/tags/{tag['id']}", json={"name": "Retro-Chic"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Retro-Chic"

    other = client.post(f"{API}/tags", json={"name": "Other"}, headers=auth).json()
    assert client.patch(
        f"{API}/tags/{other['id']}", json={"name": "retro-chic"}, headers=auth
    ).status_code == 409
    # Case-only rename of a tag onto itself is allowed.
    assert client.patch(
        f"{API}/tags/{tag['id']}", json={"name": "RETRO-CHIC"}, headers=auth
    ).status_code == 200

    for tag_id in (tag["id"], other["id"]):
        assert client.delete(f"{API}/tags/{tag_id}", headers=auth).status_code == 204
    assert _tag_by_name(client, auth, "retro-chic") is None
    assert client.delete(f"{API}/tags/999999", headers=auth).status_code == 404
    assert client.patch(f"{API}/tags/999999", json={"name": "X"}, headers=auth).status_code == 404


def test_tags_listed_name_ordered(client, auth):
    for name in ("zzz-order", "AAA-Order", "mmm-order"):
        assert client.post(f"{API}/tags", json={"name": name}, headers=auth).status_code == 201
    names = [t["name"] for t in client.get(f"{API}/tags", headers=auth).json()]
    ours = [n for n in names if n.lower().endswith("-order")]
    assert ours == ["AAA-Order", "mmm-order", "zzz-order"]  # NOCASE name order


def test_put_entity_tags_create_on_type_dedup_and_usage(client, auth):
    e = _entity(client, auth, "TagTarget")
    body = _put_tags(client, auth, e["id"], ["Alpha", " alpha ", "Beta"])
    assert [t["name"] for t in body["tags"]] == ["Alpha", "Beta"]  # payload deduped NOCASE
    assert all(set(t.keys()) == {"id", "name", "color"} for t in body["tags"])

    assert _tag_by_name(client, auth, "Alpha")["usage_count"] == 1
    assert _tag_by_name(client, auth, "Beta")["usage_count"] == 1

    # Replace-the-full-set semantics; existing tag reused case-insensitively.
    body = _put_tags(client, auth, e["id"], ["beta"])
    assert [t["name"] for t in body["tags"]] == ["Beta"]  # original casing kept
    assert _tag_by_name(client, auth, "Alpha")["usage_count"] == 0
    assert _tag_by_name(client, auth, "Beta")["usage_count"] == 1

    # Tags appear in entity GET and tree listing.
    assert [t["name"] for t in _get_entity(client, auth, e["id"])["tags"]] == ["Beta"]
    tree_row = next(
        r for r in client.get(f"{API}/entities/tree", headers=auth).json() if r["id"] == e["id"]
    )
    assert [t["name"] for t in tree_row["tags"]] == ["Beta"]

    assert client.put(
        f"{API}/entities/999999/tags", json={"tags": ["x"]}, headers=auth
    ).status_code == 404


def test_tag_delete_cascades_associations(client, auth):
    e = _entity(client, auth, "TagCascade")
    _put_tags(client, auth, e["id"], ["Doomed"])
    tag = _tag_by_name(client, auth, "Doomed")
    assert tag["usage_count"] == 1
    assert client.delete(f"{API}/tags/{tag['id']}", headers=auth).status_code == 204
    assert _get_entity(client, auth, e["id"])["tags"] == []


def test_tag_names_reject_commas(client, auth):
    # The search filter is CSV (?tags=a,b), so commas can never be part of a name.
    resp = client.post(f"{API}/tags", json={"name": "a,b"}, headers=auth)
    assert resp.status_code == 409, resp.text
    assert "comma" in resp.json()["detail"].lower()

    ok = client.post(f"{API}/tags", json={"name": "CommaFree"}, headers=auth).json()
    assert client.patch(
        f"{API}/tags/{ok['id']}", json={"name": "still,bad"}, headers=auth
    ).status_code == 409

    # Create-on-type via the entity PUT is guarded too, before anything lands.
    e = _entity(client, auth, "CommaTagTarget")
    resp = client.put(
        f"{API}/entities/{e['id']}/tags", json={"tags": ["fine", "bad,tag"]}, headers=auth
    )
    assert resp.status_code == 409, resp.text
    assert _get_entity(client, auth, e["id"])["tags"] == []
    assert _tag_by_name(client, auth, "fine") is None

    assert client.delete(f"{API}/tags/{ok['id']}", headers=auth).status_code == 204


# --- categories ---------------------------------------------------------------


def test_category_crud_and_nocase_duplicate(client, auth):
    cat = _category(client, auth, "Electronics", icon="chip", sort_order=2)
    assert set(cat.keys()) == {"id", "name", "icon", "sort_order", "fields"}
    assert cat["fields"] is None

    assert client.post(
        f"{API}/categories", json={"name": "electronics"}, headers=auth
    ).status_code == 409

    resp = client.patch(
        f"{API}/categories/{cat['id']}", json={"icon": "bolt", "sort_order": 1}, headers=auth
    )
    assert resp.status_code == 200
    assert (resp.json()["icon"], resp.json()["sort_order"]) == ("bolt", 1)

    other = _category(client, auth, "Tools")
    assert client.patch(
        f"{API}/categories/{other['id']}", json={"name": "ELECTRONICS"}, headers=auth
    ).status_code == 409

    listed = client.get(f"{API}/categories", headers=auth).json()
    assert {c["name"] for c in listed} >= {"Electronics", "Tools"}

    assert client.delete(f"{API}/categories/{other['id']}", headers=auth).status_code == 204
    assert client.delete(f"{API}/categories/999999", headers=auth).status_code == 404
    assert client.delete(f"{API}/categories/{cat['id']}", headers=auth).status_code == 204


def test_field_defs_global_and_per_category(client, auth):
    cat = _category(client, auth, "Cameras")
    voltage = _field(client, auth, "Voltage", "number", cat["id"], unit="V", required=True)
    assert voltage["category_id"] == cat["id"]
    assert (voltage["unit"], voltage["required"]) == ("V", True)
    brand = _field(client, auth, "Brand", "text")  # global
    assert brand["category_id"] is None

    # with_fields lists only the category's OWN defs.
    cats = client.get(f"{API}/categories", params={"with_fields": "true"}, headers=auth).json()
    mine = next(c for c in cats if c["id"] == cat["id"])
    assert [f["name"] for f in mine["fields"]] == ["Voltage"]

    # /fields for the category = own + globals; include_global=false = own only.
    names = [
        f["name"]
        for f in client.get(
            f"{API}/fields", params={"category_id": cat["id"]}, headers=auth
        ).json()
    ]
    assert "Voltage" in names and "Brand" in names
    names = [
        f["name"]
        for f in client.get(
            f"{API}/fields",
            params={"category_id": cat["id"], "include_global": "false"},
            headers=auth,
        ).json()
    ]
    assert names == ["Voltage"]

    assert client.get(
        f"{API}/fields", params={"category_id": 999999}, headers=auth
    ).status_code == 404
    assert client.post(
        f"{API}/fields",
        json={"name": "X", "type": "text", "category_id": 999999},
        headers=auth,
    ).status_code == 404
    assert client.post(
        f"{API}/fields", json={"name": "X", "type": "banana"}, headers=auth
    ).status_code == 422

    # Cleanup for later listing assertions.
    for field_def_id in (voltage["id"], brand["id"]):
        assert client.delete(f"{API}/fields/{field_def_id}", headers=auth).status_code == 204
    assert client.delete(f"{API}/categories/{cat['id']}", headers=auth).status_code == 204


def test_field_def_unique_per_category(client, auth):
    cat_a = _category(client, auth, "UniqA")
    cat_b = _category(client, auth, "UniqB")
    _field(client, auth, "Weight", "number", cat_a["id"])
    # Same name same category -> 409; same name other category / global -> fine.
    resp = client.post(
        f"{API}/fields",
        json={"name": "Weight", "type": "number", "category_id": cat_a["id"]},
        headers=auth,
    )
    assert resp.status_code == 409
    _field(client, auth, "Weight", "number", cat_b["id"])
    g = _field(client, auth, "Weight", "number")  # global namespace is separate
    assert client.post(
        f"{API}/fields", json={"name": "Weight", "type": "number"}, headers=auth
    ).status_code == 409  # ...but unique among globals

    assert client.delete(f"{API}/fields/{g['id']}", headers=auth).status_code == 204
    for cat in (cat_a, cat_b):
        assert client.delete(f"{API}/categories/{cat['id']}", headers=auth).status_code == 204


def test_category_delete_cascades_defs_values_and_nulls_entities(client, auth):
    cat = _category(client, auth, "Doomed Cat")
    field_def = _field(client, auth, "Wattage", "number", cat["id"])
    e = _entity(client, auth, "Categorized")
    resp = client.patch(
        f"{API}/entities/{e['id']}", json={"category_id": cat["id"]}, headers=auth
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["category_id"] == cat["id"]
    assert _put_fields(
        client, auth, e["id"], [{"field_def_id": field_def["id"], "value": "60"}]
    ).status_code == 200

    assert client.delete(f"{API}/categories/{cat['id']}", headers=auth).status_code == 204
    assert _get_entity(client, auth, e["id"])["category_id"] is None
    assert client.get(f"{API}/entities/{e['id']}/fields", headers=auth).json() == []
    all_defs = client.get(f"{API}/fields", headers=auth).json()
    assert field_def["id"] not in [f["id"] for f in all_defs]


def test_patch_entity_unknown_category_404(client, auth):
    e = _entity(client, auth, "BadCat")
    assert client.patch(
        f"{API}/entities/{e['id']}", json={"category_id": 999999}, headers=auth
    ).status_code == 404


# --- field values -------------------------------------------------------------


@pytest.fixture(scope="module")
def defs(client, auth):
    """One def per type (module-scoped; created once)."""
    return {
        "number": _field(client, auth, "FV Number", "number"),
        "date": _field(client, auth, "FV Date", "date"),
        "url": _field(client, auth, "FV Url", "url"),
        "text": _field(client, auth, "FV Text", "text"),
    }


def test_field_values_coercion_happy_paths(client, auth, defs):
    e = _entity(client, auth, "FieldsHappy")
    resp = _put_fields(
        client,
        auth,
        e["id"],
        [
            {"field_def_id": defs["number"]["id"], "value": " 42 "},
            {"field_def_id": defs["date"]["id"], "value": "2025-03-01"},
            {"field_def_id": defs["url"]["id"], "value": "https://example.com/x"},
            {"field_def_id": defs["text"]["id"], "value": "free text"},
        ],
    )
    assert resp.status_code == 200, resp.text
    rows = {r["def"]["name"]: r for r in resp.json()}
    assert set(rows["FV Number"].keys()) == {"def", "value_text", "value_num", "value_date"}
    assert (rows["FV Number"]["value_text"], rows["FV Number"]["value_num"]) == ("42", 42.0)
    assert rows["FV Number"]["value_date"] is None
    assert (rows["FV Date"]["value_text"], rows["FV Date"]["value_date"]) == (
        "2025-03-01", "2025-03-01",
    )
    assert rows["FV Url"]["value_text"] == "https://example.com/x"
    assert rows["FV Text"]["value_text"] == "free text"

    # Decimal numbers keep their canonical decimal form.
    resp = _put_fields(
        client, auth, e["id"], [{"field_def_id": defs["number"]["id"], "value": "3.50"}]
    )
    assert resp.json()[0]["value_text"] == "3.5"
    assert resp.json()[0]["value_num"] == 3.5

    # GET matches PUT's response.
    got = client.get(f"{API}/entities/{e['id']}/fields", headers=auth).json()
    assert [r["def"]["id"] for r in got] == [defs["number"]["id"]]


@pytest.mark.parametrize(
    "def_key,bad",
    [
        ("number", "abc"),
        ("number", "nan"),
        ("date", "2025-13-40"),
        ("date", "March 5"),
        ("date", "05-03-2025"),
        ("url", "ftp://example.com"),
        ("url", "example.com"),
    ],
)
def test_field_values_bad_coercion_422(client, auth, defs, def_key, bad):
    e = _entity(client, auth, f"Fields422-{def_key}-{bad[:8]}")
    resp = _put_fields(
        client, auth, e["id"], [{"field_def_id": defs[def_key]["id"], "value": bad}]
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]


def test_field_values_replace_and_empty_removes(client, auth, defs):
    e = _entity(client, auth, "FieldsReplace")
    assert _put_fields(
        client,
        auth,
        e["id"],
        [
            {"field_def_id": defs["text"]["id"], "value": "keep"},
            {"field_def_id": defs["number"]["id"], "value": "7"},
        ],
    ).status_code == 200

    # PUT with a subset removes what is absent (full-set replace).
    resp = _put_fields(
        client, auth, e["id"], [{"field_def_id": defs["text"]["id"], "value": "kept"}]
    )
    assert [r["def"]["id"] for r in resp.json()] == [defs["text"]["id"]]

    # Empty string removes the entry.
    resp = _put_fields(
        client, auth, e["id"], [{"field_def_id": defs["text"]["id"], "value": "  "}]
    )
    assert resp.json() == []

    assert _put_fields(
        client, auth, e["id"], [{"field_def_id": 999999, "value": "x"}]
    ).status_code == 404
    assert _put_fields(client, auth, 999999, []).status_code == 404
    assert client.get(f"{API}/entities/999999/fields", headers=auth).status_code == 404


def test_autocomplete_frequency_order(client, auth):
    brand = _field(client, auth, "AC Brand", "text")
    root = _entity(client, auth, "AC Root")
    for i, value in enumerate(["Nikon", "Nikon", "Canon", "Sony"]):
        e = _entity(client, auth, f"AC Item {i}", kind="item", parent_id=root["id"])
        assert _put_fields(
            client, auth, e["id"], [{"field_def_id": brand["id"], "value": value}]
        ).status_code == 200

    values = client.get(f"{API}/fields/{brand['id']}/values", headers=auth).json()
    assert values == ["Nikon", "Canon", "Sony"]  # frequency desc, then alphabetical
    values = client.get(
        f"{API}/fields/{brand['id']}/values", params={"q": "ca"}, headers=auth
    ).json()
    assert values == ["Canon"]
    values = client.get(
        f"{API}/fields/{brand['id']}/values", params={"limit": 1}, headers=auth
    ).json()
    assert values == ["Nikon"]
    assert client.get(f"{API}/fields/999999/values", headers=auth).status_code == 404


def test_field_type_change_recoerces_stored_values(client, auth):
    field_def = _field(client, auth, "Morphable", "text")
    root = _entity(client, auth, "Morph Root")
    num_e = _entity(client, auth, "Morph Numeric", kind="item", parent_id=root["id"])
    txt_e = _entity(client, auth, "Morph Texty", kind="item", parent_id=root["id"])
    assert _put_fields(
        client, auth, num_e["id"], [{"field_def_id": field_def["id"], "value": "42"}]
    ).status_code == 200
    assert _put_fields(
        client, auth, txt_e["id"], [{"field_def_id": field_def["id"], "value": "abc"}]
    ).status_code == 200

    resp = client.patch(
        f"{API}/fields/{field_def['id']}", json={"type": "number"}, headers=auth
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["type"] == "number"

    row = client.get(f"{API}/entities/{num_e['id']}/fields", headers=auth).json()[0]
    assert (row["value_text"], row["value_num"]) == ("42", 42.0)
    row = client.get(f"{API}/entities/{txt_e['id']}/fields", headers=auth).json()[0]
    assert (row["value_text"], row["value_num"]) == ("abc", None)  # uncoercible -> NULL


def test_entity_delete_cascades_tags_and_field_values(client, auth, defs):
    from sqlalchemy import select

    from app.database import get_sessionmaker
    from app.models.metadata import EntityTag, FieldValue

    root = _entity(client, auth, "CascadeDel Root")
    e = _entity(client, auth, "CascadeDel Item", kind="item", parent_id=root["id"])
    _put_tags(client, auth, e["id"], ["Zundertag"])
    assert _put_fields(
        client, auth, e["id"], [{"field_def_id": defs["text"]["id"], "value": "zunderval"}]
    ).status_code == 200

    def _hits(q):
        resp = client.get(f"{API}/search", params={"q": q}, headers=auth)
        assert resp.status_code == 200, resp.text
        return [r["id"] for r in resp.json()["results"]]

    assert e["id"] in _hits("zundertag")
    assert e["id"] in _hits("zunderval")

    assert client.delete(f"{API}/entities/{e['id']}", headers=auth).status_code == 204

    # The FK cascades removed the association/value rows...
    with get_sessionmaker()() as db:
        assert db.scalars(
            select(EntityTag).where(EntityTag.entity_id == e["id"])
        ).first() is None
        assert db.scalars(
            select(FieldValue).where(FieldValue.entity_id == e["id"])
        ).first() is None
    # ...and the fts row went with the entity: old tag/field text finds nothing.
    assert _hits("zundertag") == []
    assert _hits("zunderval") == []


# --- duplicate ----------------------------------------------------------------


def test_duplicate_copies_everything_but_the_exclusions(client, auth, defs):
    from app.database import get_sessionmaker
    from app.models.entity import Entity

    cat = _category(client, auth, "Dup Cat")
    root = _entity(client, auth, "Dup Root")
    src = _entity(client, auth, "Dup Widget", kind="item", parent_id=root["id"])
    client.patch(f"{API}/entities/{src['id']}", json={"category_id": cat["id"]}, headers=auth)
    _put_tags(client, auth, src["id"], ["DupTagA", "DupTagB"])
    assert _put_fields(
        client, auth, src["id"], [{"field_def_id": defs["text"]["id"], "value": "copied"}]
    ).status_code == 200

    # Inventory columns + asset_tag have no M4 endpoints — set them directly.
    with get_sessionmaker()() as db:
        row = db.get(Entity, src["id"])
        row.asset_tag = "AT-DUP-0001"
        row.quantity = 3
        row.unit = "pcs"
        row.is_consumable = True
        row.low_stock_threshold = 1.5
        row.purchase_date = "2024-05-01"
        row.purchase_price = 99.5
        row.purchase_from = "ACME"
        row.currency = "EUR"
        row.current_value = 80
        row.insured = True
        row.warranty_expires = "2027-05-01"
        row.warranty_lifetime = False
        row.warranty_notes = "extended"
        row.serial_number = "SN-1"
        row.model_number = "MN-1"
        row.manufacturer = "Widgets Inc"
        row.sold_date = "2026-01-01"
        row.sold_to = "Bob"
        row.sold_price = 70
        row.sold_notes = "as-is"
        db.commit()

    # An attachment that must NOT travel with the copy.
    assert client.post(
        f"{API}/entities/{src['id']}/attachments",
        files={"file": ("p.jpg", _jpeg(color=(33, 44, 55)), "application/octet-stream")},
        headers=auth,
    ).status_code == 201

    resp = client.post(f"{API}/entities/{src['id']}/duplicate", headers=auth)
    assert resp.status_code == 201, resp.text
    dup = resp.json()
    assert dup["id"] != src["id"]
    assert dup["name"] == "Dup Widget (copy)"
    assert dup["kind"] == "item"
    assert dup["parent_id"] == root["id"]
    assert dup["breadcrumb"] == "Dup Root › Dup Widget (copy)"
    assert dup["category_id"] == cat["id"]
    assert [t["name"] for t in dup["tags"]] == ["DupTagA", "DupTagB"]
    assert dup["asset_tag"] is None  # unique column never copied
    assert dup["draft"] is False
    assert dup["archived"] is False
    assert dup["child_count"] == 0

    fields = client.get(f"{API}/entities/{dup['id']}/fields", headers=auth).json()
    assert [(r["def"]["id"], r["value_text"]) for r in fields] == [
        (defs["text"]["id"], "copied")
    ]
    assert client.get(f"{API}/entities/{dup['id']}/attachments", headers=auth).json() == []

    with get_sessionmaker()() as db:
        row = db.get(Entity, dup["id"])
        assert (row.quantity, row.unit, row.is_consumable) == (3, "pcs", True)
        assert (row.low_stock_threshold, row.purchase_date) == (1.5, "2024-05-01")
        assert (row.purchase_price, row.purchase_from, row.currency) == (99.5, "ACME", "EUR")
        assert (row.current_value, row.insured) == (80, True)
        assert (row.warranty_expires, row.warranty_lifetime, row.warranty_notes) == (
            "2027-05-01", False, "extended",
        )
        assert (row.serial_number, row.model_number, row.manufacturer) == (
            "SN-1", "MN-1", "Widgets Inc",
        )
        assert (row.sold_date, row.sold_to, row.sold_price, row.sold_notes) == (
            "2026-01-01", "Bob", 70, "as-is",
        )
        assert row.asset_tag is None


def test_duplicate_does_not_copy_children(client, auth):
    root = _entity(client, auth, "DupKids Root")
    box = _entity(client, auth, "DupKids Box", kind="container", parent_id=root["id"])
    _entity(client, auth, "DupKids Item", kind="item", parent_id=box["id"])
    dup = client.post(f"{API}/entities/{box['id']}/duplicate", headers=auth).json()
    assert dup["child_count"] == 0
    assert client.get(f"{API}/entities/{dup['id']}/children", headers=auth).json() == []


def test_duplicate_copies_typed_values_not_import_ref(client, auth, defs):
    from app.database import get_sessionmaker
    from app.models.entity import Entity

    root = _entity(client, auth, "DupTyped Root")
    src = _entity(client, auth, "DupTyped Widget", kind="item", parent_id=root["id"])
    assert _put_fields(
        client,
        auth,
        src["id"],
        [
            {"field_def_id": defs["number"]["id"], "value": "12.5"},
            {"field_def_id": defs["date"]["id"], "value": "2025-06-15"},
        ],
    ).status_code == 200
    with get_sessionmaker()() as db:  # import_ref has no API — set it directly
        db.get(Entity, src["id"]).import_ref = "import-batch-7"
        db.commit()

    resp = client.post(f"{API}/entities/{src['id']}/duplicate", headers=auth)
    assert resp.status_code == 201, resp.text
    dup = resp.json()

    rows = {
        r["def"]["id"]: r
        for r in client.get(f"{API}/entities/{dup['id']}/fields", headers=auth).json()
    }
    number = rows[defs["number"]["id"]]
    assert (number["value_text"], number["value_num"], number["value_date"]) == (
        "12.5", 12.5, None,
    )
    day = rows[defs["date"]["id"]]
    assert (day["value_text"], day["value_num"], day["value_date"]) == (
        "2025-06-15", None, "2025-06-15",
    )
    with get_sessionmaker()() as db:
        assert db.get(Entity, dup["id"]).import_ref is None
        assert db.get(Entity, src["id"]).import_ref == "import-batch-7"


def test_duplicate_inbox_409_and_unknown_404(client, auth):
    rows = client.get(f"{API}/entities/tree", headers=auth).json()
    inbox = next(e for e in rows if e["protected"])
    assert client.post(f"{API}/entities/{inbox['id']}/duplicate", headers=auth).status_code == 409
    assert client.post(f"{API}/entities/999999/duplicate", headers=auth).status_code == 404


# --- presets ------------------------------------------------------------------


def test_preset_crud(client, auth):
    payload = {"category_id": 1, "fields": [{"name": "Voltage", "value": "230"}]}
    resp = client.post(
        f"{API}/presets", json={"name": "Camera kit", "payload": payload}, headers=auth
    )
    assert resp.status_code == 201, resp.text
    preset = resp.json()
    assert set(preset.keys()) == {"id", "name", "payload"}
    assert preset["payload"] == payload  # JSON round-trips through TEXT storage

    assert client.post(
        f"{API}/presets", json={"name": "Camera kit", "payload": {}}, headers=auth
    ).status_code == 409

    resp = client.patch(
        f"{API}/presets/{preset['id']}", json={"payload": {"v": 2}}, headers=auth
    )
    assert resp.status_code == 200
    assert resp.json()["payload"] == {"v": 2}
    assert resp.json()["name"] == "Camera kit"

    resp = client.patch(f"{API}/presets/{preset['id']}", json={"name": "Lens kit"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Lens kit"

    listed = client.get(f"{API}/presets", headers=auth).json()
    assert any(p["id"] == preset["id"] for p in listed)

    assert client.delete(f"{API}/presets/{preset['id']}", headers=auth).status_code == 204
    assert client.delete(f"{API}/presets/{preset['id']}", headers=auth).status_code == 404
    assert client.patch(
        f"{API}/presets/999999", json={"name": "X"}, headers=auth
    ).status_code == 404
