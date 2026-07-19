"""M6 IO tests: CSV export/import (round trip, location resolution, tags,
fields, asset tags, dry_run, error handling, HomeBox dialect), backups
(VACUUM INTO snapshot, prune, endpoints), export.zip and the scheduler.

The exact-header tests run FIRST in this module on purpose: no earlier test
module creates field values or asset tags, so the dynamic columns
(field:<Name> / HB.field.<Name> / HB.asset_id) are provably absent."""

import csv
import io
import sqlite3
import zipfile

import pytest
from PIL import Image

API = "/api/v1"

OUR_COLUMNS = [
    "import_ref", "name", "kind", "subtype", "location", "category", "tags",
    "quantity", "unit", "is_consumable", "low_stock_threshold", "purchase_date",
    "purchase_price", "purchase_from", "currency", "current_value", "insured",
    "warranty_expires", "warranty_lifetime", "warranty_notes", "serial_number",
    "model_number", "manufacturer", "description", "notes", "asset_tag",
]

HOMEBOX_BASE = [
    "HB.import_ref", "HB.location", "HB.name", "HB.quantity", "HB.archived",
    "HB.insured", "HB.notes", "HB.purchase_from", "HB.purchase_price",
    "HB.purchase_date", "HB.manufacturer", "HB.model_number", "HB.serial_number",
    "HB.lifetime_warranty", "HB.warranty_expires", "HB.warranty_details", "HB.tags",
]


@pytest.fixture(scope="module")
def auth(client, test_user):
    """One login for the whole module (same pattern as test_tree)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make(client, auth, name, kind, parent_id=None):
    resp = client.post(
        f"{API}/entities",
        json={"name": name, "kind": kind, "parent_id": parent_id},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _get(client, auth, entity_id):
    resp = client.get(f"{API}/entities/{entity_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _export(client, auth, dialect=None):
    params = {"dialect": dialect} if dialect else None
    resp = client.get(f"{API}/admin/export.csv", params=params, headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.text


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


def _import(client, auth, text, dry_run=False, expect=200):
    resp = client.post(
        f"{API}/admin/import-csv",
        params={"dry_run": "true"} if dry_run else None,
        files={"file": ("import.csv", text.encode("utf-8"), "text/csv")},
        headers=auth,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _csv(header, *rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _entity_count():
    from sqlalchemy import func, select

    from app.database import get_sessionmaker
    from app.models.entity import Entity

    with get_sessionmaker()() as db:
        return db.scalar(select(func.count(Entity.id)))


def _stored_ref(entity_id):
    from sqlalchemy import select

    from app.database import get_sessionmaker
    from app.models.entity import Entity

    with get_sessionmaker()() as db:
        return db.scalar(select(Entity.import_ref).where(Entity.id == entity_id))


def _data_dir():
    from app.config import get_settings

    return get_settings().data_dir


# --- exact headers (MUST run before any field values / asset tags exist) ------


def test_export_csv_headers_exact(client, auth):
    header = _rows(_export(client, auth))[0]
    assert header == OUR_COLUMNS  # no field defs in use yet -> no field: columns


def test_export_homebox_headers_exact(client, auth):
    header = _rows(_export(client, auth, dialect="homebox"))[0]
    assert header == HOMEBOX_BASE  # no asset tags yet -> HB.asset_id omitted


def test_export_requires_auth(client):
    assert client.get(f"{API}/admin/export.csv").status_code == 401
    assert client.post(f"{API}/admin/import-csv").status_code == 401
    assert client.get(f"{API}/admin/export.zip").status_code == 401
    assert client.post(f"{API}/admin/backup-now").status_code == 401
    assert client.get(f"{API}/admin/backups").status_code == 401


# --- import basics ------------------------------------------------------------


def test_import_creates_with_location_autocreate(client, auth):
    before = _entity_count()
    result = _import(client, auth, _csv(
        ["import_ref", "name", "kind", "location"],
        ["io-auto-1", "IoAutoItem", "item", "IoAutoA / IoAutoB"],
    ))
    assert result == {"created": 1, "updated": 0, "errors": [], "dry_run": False}
    # The row entity plus the two auto-created spaces.
    assert _entity_count() == before + 3

    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    by_name = {e["name"]: e for e in tree_rows}
    assert by_name["IoAutoA"]["kind"] == "space"
    assert by_name["IoAutoA"]["parent_id"] is None
    assert by_name["IoAutoB"]["kind"] == "space"
    assert by_name["IoAutoB"]["parent_id"] == by_name["IoAutoA"]["id"]
    item = by_name["IoAutoItem"]
    assert item["kind"] == "item"
    assert item["parent_id"] == by_name["IoAutoB"]["id"]
    # import_ref stored: a re-import updates instead of duplicating.
    again = _import(client, auth, _csv(
        ["import_ref", "name", "kind", "location"],
        ["io-auto-1", "IoAutoItem", "item", "IoAutoA / IoAutoB"],
    ))
    assert again["created"] == 0 and again["updated"] == 1
    assert _entity_count() == before + 3


def test_import_location_match_is_case_insensitive(client, auth):
    root = _make(client, auth, "IoCaseRoot", "space")
    result = _import(client, auth, _csv(
        ["name", "kind", "location"],
        ["IoCaseItem", "item", "iocaseroot"],
    ))
    assert result["created"] == 1 and result["errors"] == []
    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    roots = [e for e in tree_rows if e["name"].lower() == "iocaseroot"]
    assert len(roots) == 1  # matched, not duplicated
    item = next(e for e in tree_rows if e["name"] == "IoCaseItem")
    assert item["parent_id"] == root["id"]


def test_import_move_via_location_change(client, auth):
    a = _make(client, auth, "IoMoveA", "space")
    b = _make(client, auth, "IoMoveB", "space")
    item = _make(client, auth, "IoMoveItem", "item", a["id"])

    result = _import(client, auth, _csv(
        ["import_ref", "name", "location"],
        [f"arch-{item['id']}", "IoMoveItem", "IoMoveB"],  # generated-ref fallback
    ))
    assert result == {"created": 0, "updated": 1, "errors": [], "dry_run": False}
    moved = _get(client, auth, item["id"])
    assert moved["parent_id"] == b["id"]
    assert moved["breadcrumb"] == "IoMoveB › IoMoveItem"

    # Containment still enforced: an item cannot move to the root level.
    result = _import(client, auth, _csv(
        ["import_ref", "name", "location"],
        [f"arch-{item['id']}", "IoMoveItem", ""],
    ))
    assert result["updated"] == 0
    assert len(result["errors"]) == 1
    assert _get(client, auth, item["id"])["parent_id"] == b["id"]


def test_import_replaces_tags(client, auth):
    root = _make(client, auth, "IoTagRoot", "space")
    item = _make(client, auth, "IoTagItem", "item", root["id"])
    put = client.put(
        f"{API}/entities/{item['id']}/tags",
        json={"tags": ["IoOld", "IoKeep"]},
        headers=auth,
    )
    assert put.status_code == 200, put.text

    result = _import(client, auth, _csv(
        ["import_ref", "name", "tags"],
        [f"arch-{item['id']}", "IoTagItem", "IoKeep;IoNew"],
    ))
    assert result["updated"] == 1 and result["errors"] == []
    names = {t["name"] for t in _get(client, auth, item["id"])["tags"]}
    assert names == {"IoKeep", "IoNew"}


def test_import_inventory_fields_and_validation(client, auth):
    root = _make(client, auth, "IoInvRoot", "space")
    result = _import(client, auth, _csv(
        ["name", "kind", "location", "quantity", "is_consumable", "purchase_price",
         "currency", "purchase_date"],
        ["IoInvGood", "item", "IoInvRoot", "4", "true", "9.5", "CHF", "2025-03-04"],
        ["IoInvBadDate", "item", "IoInvRoot", "1", "false", "1", "CHF", "04.03.2025"],
        ["IoInvBadPrice", "item", "IoInvRoot", "1", "false", "-2", "CHF", "2025-03-04"],
        ["IoInvBadCurrency", "item", "IoInvRoot", "1", "false", "1", "chf", "2025-03-04"],
    ))
    assert result["created"] == 1
    assert sorted(e["row"] for e in result["errors"]) == [2, 3, 4]
    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    good = next(e for e in tree_rows if e["name"] == "IoInvGood")
    assert good["parent_id"] == root["id"]
    assert good["quantity"] == 4
    assert good["is_consumable"] is True
    assert good["purchase_price"] == 9.5
    assert good["currency"] == "CHF"
    assert good["purchase_date"] == "2025-03-04"
    assert not any(e["name"].startswith("IoInvBad") for e in tree_rows)


def test_import_field_values_upsert_and_unknown_field(client, auth):
    cat = client.post(f"{API}/categories", json={"name": "IoCat"}, headers=auth).json()
    volt = client.post(
        f"{API}/fields",
        json={"category_id": cat["id"], "name": "IoVolt", "type": "number"},
        headers=auth,
    ).json()
    note = client.post(
        f"{API}/fields", json={"category_id": None, "name": "IoNote", "type": "text"},
        headers=auth,
    ).json()
    assert volt["id"] and note["id"]

    _make(client, auth, "IoFieldRoot", "space")
    result = _import(client, auth, _csv(
        ["name", "kind", "location", "category", "field:IoVolt", "field:IoNote",
         "field:IoBogus"],
        ["IoFieldItem", "item", "IoFieldRoot", "IoCat", "230", "hello", ""],
        ["IoFieldBad", "item", "IoFieldRoot", "IoCat", "230", "hello", "boom"],
    ))
    assert result["created"] == 1
    assert [e["row"] for e in result["errors"]] == [2]
    assert "IoBogus" in result["errors"][0]["message"]

    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    item = next(e for e in tree_rows if e["name"] == "IoFieldItem")
    fields = client.get(f"{API}/entities/{item['id']}/fields", headers=auth).json()
    by_name = {f["def"]["name"]: f for f in fields}
    assert by_name["IoVolt"]["value_num"] == 230
    assert by_name["IoNote"]["value_text"] == "hello"

    # Upsert: a second import overwrites the number, clears the note.
    result = _import(client, auth, _csv(
        ["import_ref", "name", "field:IoVolt", "field:IoNote"],
        [f"arch-{item['id']}", "IoFieldItem", "115", ""],
    ))
    assert result["updated"] == 1 and result["errors"] == []
    fields = client.get(f"{API}/entities/{item['id']}/fields", headers=auth).json()
    by_name = {f["def"]["name"]: f for f in fields}
    assert by_name["IoVolt"]["value_num"] == 115
    assert "IoNote" not in by_name


def test_import_asset_tag_assign_and_collision(client, auth):
    _make(client, auth, "IoAssetRoot", "space")
    result = _import(client, auth, _csv(
        ["name", "kind", "location", "asset_tag"],
        ["IoAssetOne", "item", "IoAssetRoot", "IO-0001"],
        ["IoAssetTwo", "item", "IoAssetRoot", "IO-0001"],  # collision -> row error
        ["IoAssetThree", "item", "IoAssetRoot", "IO-0002"],
    ))
    assert result["created"] == 2
    assert [e["row"] for e in result["errors"]] == [2]

    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    one = next(e for e in tree_rows if e["name"] == "IoAssetOne")
    three = next(e for e in tree_rows if e["name"] == "IoAssetThree")
    assert one["asset_tag"] == "IO-0001"
    assert three["asset_tag"] == "IO-0002"
    assert not any(e["name"] == "IoAssetTwo" for e in tree_rows)  # row rolled back whole


def test_import_dry_run_creates_nothing(client, auth):
    before = _entity_count()
    text = _csv(
        ["name", "kind", "location", "tags"],
        ["IoDryItemA", "item", "IoDryRoot", "IoDryTag"],
        ["IoDryItemB", "container", "IoDryRoot", ""],
        ["IoDryBad", "gizmo", "IoDryRoot", ""],  # bad kind -> would-be error
    )
    result = _import(client, auth, text, dry_run=True)
    assert result["dry_run"] is True
    assert result["created"] == 2
    assert result["updated"] == 0
    assert len(result["errors"]) == 1
    assert _entity_count() == before  # NOTHING persisted, not even IoDryRoot
    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    assert not any(e["name"].startswith("IoDry") for e in tree_rows)

    # The same file applied for real: rows + the auto-created root.
    result = _import(client, auth, text)
    assert result["dry_run"] is False
    assert result["created"] == 2
    assert _entity_count() == before + 3


def test_import_malformed_header_422(client, auth):
    _import(client, auth, _csv(["name", "bogus_column"]), expect=422)
    _import(client, auth, _csv(["kind", "location"]), expect=422)  # no name
    _import(client, auth, _csv(["name", "name"]), expect=422)  # duplicate
    _import(client, auth, "", expect=422)  # empty file


def test_import_error_rows_do_not_abort_others(client, auth):
    root = _make(client, auth, "IoErrRoot", "space")
    assert root["id"]
    result = _import(client, auth, _csv(
        ["name", "kind", "location"],
        ["IoErrOk1", "item", "IoErrRoot"],
        ["IoErrBad", "notakind", "IoErrRoot"],
        ["", "item", "IoErrRoot"],  # blank name
        ["IoErrOk2", "item", "IoErrRoot"],
    ))
    assert result["created"] == 2
    assert sorted(e["row"] for e in result["errors"]) == [2, 3]
    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    names = {e["name"] for e in tree_rows}
    assert {"IoErrOk1", "IoErrOk2"} <= names
    assert "IoErrBad" not in names


# --- arch- fallback safety ----------------------------------------------------


def test_import_arch_ref_never_rebinds_a_stored_ref(client, auth):
    _make(client, auth, "IoRefRoot", "space")
    seeded = _import(client, auth, _csv(
        ["import_ref", "name", "kind", "location"],
        ["homebox-77", "IoRefKeep", "item", "IoRefRoot"],
    ))
    assert seeded["created"] == 1 and seeded["errors"] == []
    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    entity = next(e for e in tree_rows if e["name"] == "IoRefKeep")
    assert _stored_ref(entity["id"]) == "homebox-77"

    result = _import(client, auth, _csv(
        ["import_ref", "name"],
        [f"arch-{entity['id']}", "IoRefHijack"],
    ))
    assert result["created"] == 0 and result["updated"] == 0
    assert len(result["errors"]) == 1
    assert "conflicts with existing ref 'homebox-77'" in result["errors"][0]["message"]
    # Entity untouched: name AND stored ref survive.
    assert _get(client, auth, entity["id"])["name"] == "IoRefKeep"
    assert _stored_ref(entity["id"]) == "homebox-77"


def test_import_arch_ref_cannot_address_the_inbox(client, auth):
    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    inbox = next(e for e in tree_rows if e["protected"])

    result = _import(client, auth, _csv(
        ["import_ref", "name"],
        [f"arch-{inbox['id']}", "IoInboxHijack"],
    ))
    assert result["created"] == 0 and result["updated"] == 0
    assert len(result["errors"]) == 1
    assert "Inbox" in result["errors"][0]["message"]
    assert _get(client, auth, inbox["id"])["name"] == inbox["name"]  # untouched
    assert _stored_ref(inbox["id"]) is None


def test_import_arch_ref_overflow_is_row_error_not_500(client, auth):
    _make(client, auth, "IoOvRoot", "space")
    result = _import(client, auth, _csv(
        ["import_ref", "name", "kind", "location"],
        ["arch-99999999999999999999", "IoOvBad", "item", "IoOvRoot"],
        ["io-ov-ok", "IoOvGood", "item", "IoOvRoot"],
    ))
    assert result["created"] == 1  # the import carried on with the other rows
    assert [e["row"] for e in result["errors"]] == [1]
    tree_rows = client.get(f"{API}/entities/tree", headers=auth).json()
    names = {e["name"] for e in tree_rows}
    assert "IoOvGood" in names
    assert "IoOvBad" not in names


def test_import_kind_change_is_row_error(client, auth):
    root = _make(client, auth, "IoKindRoot", "space")
    item = _make(client, auth, "IoKindItem", "item", root["id"])
    result = _import(client, auth, _csv(
        ["import_ref", "name", "kind"],
        [f"arch-{item['id']}", "IoKindItem", "container"],
    ))
    assert result["updated"] == 0
    assert len(result["errors"]) == 1
    assert "kind change from item to container is not supported" in (
        result["errors"][0]["message"]
    )
    assert _get(client, auth, item["id"])["kind"] == "item"


def test_import_update_row_late_failure_rolls_back_whole_row(client, auth):
    root = _make(client, auth, "IoLateRoot", "space")
    holder = _make(client, auth, "IoLateHolder", "item", root["id"])
    victim = _make(client, auth, "IoLateVictim", "item", root["id"])
    put = client.put(
        f"{API}/entities/{victim['id']}/tags", json={"tags": ["IoLateOld"]}, headers=auth
    )
    assert put.status_code == 200, put.text
    seeded = _import(client, auth, _csv(
        ["import_ref", "name", "asset_tag"],
        [f"arch-{holder['id']}", "IoLateHolder", "IO-LATE-1"],
    ))
    assert seeded["errors"] == []

    # Tags would be replaced FIRST, then the colliding asset_tag fails the row:
    # the savepoint must roll the tag replacement back with everything else.
    result = _import(client, auth, _csv(
        ["import_ref", "name", "tags", "asset_tag"],
        [f"arch-{victim['id']}", "IoLateVictim", "IoLateNew", "IO-LATE-1"],
    ))
    assert result["updated"] == 0
    assert len(result["errors"]) == 1
    got = _get(client, auth, victim["id"])
    assert {t["name"] for t in got["tags"]} == {"IoLateOld"}
    assert got["asset_tag"] is None


# --- formula-injection guard --------------------------------------------------


def test_export_formula_guard_round_trip(client, auth):
    root = _make(client, auth, "IoFormRoot", "space")
    name = '=HYPERLINK("http://x")'
    item = _make(client, auth, name, "item", root["id"])

    text = _export(client, auth)
    rows = _rows(text)
    idx = {c: i for i, c in enumerate(rows[0])}
    row = next(r for r in rows[1:] if r[idx["import_ref"]] == f"arch-{item['id']}")
    assert row[idx["name"]] == "'" + name  # guarded on export

    result = _import(client, auth, text)
    assert all("Inbox" in e["message"] for e in result["errors"])  # only the Inbox row
    assert _get(client, auth, item["id"])["name"] == name  # exact original restored

    # Idempotent: exporting again still yields the guarded cell, importing again
    # still restores the same name (no quote accumulation).
    text2 = _export(client, auth)
    row2 = next(
        r for r in _rows(text2)[1:] if r[idx["import_ref"]] == f"arch-{item['id']}"
    )
    assert row2[idx["name"]] == "'" + name
    result = _import(client, auth, text2)
    assert all("Inbox" in e["message"] for e in result["errors"])
    assert _get(client, auth, item["id"])["name"] == name


# --- round trip ---------------------------------------------------------------


def test_export_import_round_trip_is_idempotent(client, auth):
    # A small tree exercising every column family.
    root = _make(client, auth, "IoRtRoot", "space")
    shelf = _make(client, auth, "IoRtShelf", "furniture", root["id"])
    box = _make(client, auth, "IoRtBox", "container", shelf["id"])
    item = _make(client, auth, "IoRtItem", "item", box["id"])
    client.patch(f"{API}/entities/{item['id']}", json={
        "description": "round trip", "notes": "n1", "quantity": 7, "unit": "pcs",
        "is_consumable": True, "low_stock_threshold": 2, "purchase_date": "2025-05-05",
        "purchase_price": 12.5, "currency": "EUR", "insured": True,
        "serial_number": "RT-1",
    }, headers=auth)
    client.put(f"{API}/entities/{item['id']}/tags", json={"tags": ["IoRtTag"]}, headers=auth)

    text = _export(client, auth)
    rows = _rows(text)
    data_rows = len(rows) - 1
    assert data_rows == _entity_count()  # ALL kinds exported, spaces included

    before = _entity_count()
    result = _import(client, auth, text)
    # The Inbox exports with the generated arch- fallback ref, which import
    # refuses to bind (protected) — the ONE expected error; everything else
    # round-trips cleanly.
    assert len(result["errors"]) == 1
    assert "Inbox" in result["errors"][0]["message"]
    assert result["created"] == 0
    assert result["updated"] == data_rows - 1
    assert _entity_count() == before

    # Idempotent: a second pass changes nothing either.
    result = _import(client, auth, text)
    assert result["created"] == 0
    assert len(result["errors"]) == 1 and "Inbox" in result["errors"][0]["message"]
    assert _entity_count() == before

    # Spot-check the tree survived intact.
    got = _get(client, auth, item["id"])
    assert got["parent_id"] == box["id"]
    assert got["breadcrumb"] == "IoRtRoot › IoRtShelf › IoRtBox › IoRtItem"
    assert got["quantity"] == 7
    assert got["purchase_price"] == 12.5
    assert got["currency"] == "EUR"
    assert {t["name"] for t in got["tags"]} == {"IoRtTag"}
    assert _get(client, auth, box["id"])["parent_id"] == shelf["id"]


def test_export_location_and_dynamic_columns(client, auth):
    text = _export(client, auth)
    rows = _rows(text)
    header = rows[0]
    # Field defs are in use by now (created in the field-values test above).
    # IoNote is NOT here: its only value was cleared, so it is no longer in use.
    assert "field:IoVolt" in header
    assert "field:IoNote" not in header
    idx = {name: i for i, name in enumerate(header)}
    by_name = {r[idx["name"]]: r for r in rows[1:]}
    assert by_name["IoRtItem"][idx["location"]] == "IoRtRoot / IoRtShelf / IoRtBox"
    assert by_name["IoRtRoot"][idx["location"]] == ""  # roots have no location
    assert by_name["IoRtItem"][idx["is_consumable"]] == "true"
    assert by_name["IoRtRoot"][idx["is_consumable"]] == "false"
    assert by_name["IoFieldItem"][idx["field:IoVolt"]] == "115"

    hb_header = _rows(_export(client, auth, dialect="homebox"))[0]
    assert "HB.asset_id" in hb_header  # asset tags exist now
    assert "HB.field.IoVolt" in hb_header
    base = [c for c in hb_header if not c.startswith("HB.field.")]
    expected = HOMEBOX_BASE.copy()
    expected.insert(expected.index("HB.archived"), "HB.asset_id")
    assert base == expected


# --- backups ------------------------------------------------------------------


def test_run_backup_produces_valid_snapshot(client, auth):
    from app.services.backup import run_backup

    result = run_backup(_data_dir())
    assert set(result.keys()) == {"file", "bytes"}
    assert result["bytes"] > 0
    target = _data_dir() / "backups" / result["file"]
    assert target.exists()

    conn = sqlite3.connect(str(target))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        count = conn.execute("SELECT count(*) FROM entity").fetchone()[0]
        assert count > 0  # a real snapshot of the live data, not an empty db
    finally:
        conn.close()


def test_prune_keeps_newest_14(tmp_path):
    import os

    from app.services.backup import prune_backups

    for i in range(20):
        f = tmp_path / f"db-20250101-{i:06d}.db"
        f.write_bytes(b"x")
        os.utime(f, (1_700_000_000 + i, 1_700_000_000 + i))
    prune_backups(tmp_path)
    remaining = sorted(p.name for p in tmp_path.glob("db-*.db"))
    assert len(remaining) == 14
    assert remaining[0] == "db-20250101-000006.db"  # the 6 oldest pruned
    assert remaining[-1] == "db-20250101-000019.db"


def test_backup_now_and_list_endpoints(client, auth):
    resp = client.post(f"{API}/admin/backup-now", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"file", "bytes"}
    assert body["bytes"] > 0

    listing = client.get(f"{API}/admin/backups", headers=auth)
    assert listing.status_code == 200
    backups = listing.json()
    assert backups, "backup-now must show up in the listing"
    assert set(backups[0].keys()) == {"file", "bytes", "created_at"}
    assert backups[0]["file"] == body["file"]  # newest first
    files = [b["file"] for b in backups]
    assert body["file"] in files


def test_backups_created_at_is_timezone_aware_utc(client, auth):
    from datetime import datetime

    client.post(f"{API}/admin/backup-now", headers=auth)
    backups = client.get(f"{API}/admin/backups", headers=auth).json()
    assert backups
    for entry in backups:
        stamp = entry["created_at"]
        # Aware UTC ISO — the frontend's `new Date()` must not read it as local.
        assert stamp.endswith("+00:00") or stamp.endswith("Z")
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None


# --- export.zip ---------------------------------------------------------------


def test_export_zip_contents(client, auth):
    # Ensure at least one attachment file (and hence derived/ files) exists.
    e = _make(client, auth, "IoZipRoot", "space")
    buf = io.BytesIO()
    Image.new("RGB", (600, 400), (10, 90, 40)).save(buf, "JPEG", quality=90)
    up = client.post(
        f"{API}/entities/{e['id']}/attachments",
        files={"file": ("zip.jpg", buf.getvalue(), "application/octet-stream")},
        headers=auth,
    )
    assert up.status_code == 201, up.text
    assert any((_data_dir() / "derived").rglob("*")), "derived files should exist on disk"

    resp = client.get(f"{API}/admin/export.zip", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/zip")

    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = archive.namelist()
    assert "db-snapshot.db" in names
    assert any(n.startswith("attachments/") for n in names)
    assert not any(n.startswith("derived/") for n in names)  # regenerable — excluded
    # The embedded snapshot is a healthy sqlite database.
    with archive.open("db-snapshot.db") as fh:
        assert fh.read(16) == b"SQLite format 3\x00"


def test_export_zip_excludes_backups_secrets_and_wal(client, auth):
    # Pin the exclusion list: backups and the JWT secret must NEVER ship in the
    # archive, and no raw -wal journal may leak alongside the snapshot. Since
    # M9 the same holds for gdrive/ (the OAuth token — a live Drive credential)
    # and drive-cache/ (regenerable Drive thumbnails).
    assert client.post(f"{API}/admin/backup-now", headers=auth).status_code == 200
    assert (_data_dir() / "secret.key").is_file()
    gdrive_dir = _data_dir() / "gdrive"
    gdrive_dir.mkdir(exist_ok=True)
    (gdrive_dir / "token.json").write_text("{}", encoding="utf-8")  # inert fake token
    cache_dir = _data_dir() / "drive-cache"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / "zip-pin.jpg").write_bytes(b"\xff\xd8x")

    resp = client.get(f"{API}/admin/export.zip", headers=auth)
    assert resp.status_code == 200, resp.text
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert not any(n.startswith("backups/") for n in names)
    assert "secret.key" not in names
    assert not any(n.endswith(".db-wal") for n in names)
    assert not any(n.startswith("gdrive/") for n in names)
    assert not any(n.startswith("drive-cache/") for n in names)


# --- scheduler ----------------------------------------------------------------


def test_build_scheduler_registers_nightly_and_drive_poll_jobs():
    from apscheduler.triggers.interval import IntervalTrigger

    from app.config import get_settings
    from app.services.scheduler import (
        DRIVE_POLL_JOB_ID,
        NIGHTLY_JOB_ID,
        build_scheduler,
        drive_poll,
        nightly_backup,
    )

    scheduler = build_scheduler(get_settings())
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {NIGHTLY_JOB_ID, DRIVE_POLL_JOB_ID}
    job = jobs[NIGHTLY_JOB_ID]
    assert job.func is nightly_backup
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "3"
    assert fields["minute"] == "30"
    # M9: the Drive poll interval comes from drive_account.poll_interval_min.
    poll = jobs[DRIVE_POLL_JOB_ID]
    assert poll.func is drive_poll
    assert isinstance(poll.trigger, IntervalTrigger)


def test_nightly_job_body_runs_directly(client):
    from app.services.scheduler import nightly_backup

    result = nightly_backup()
    assert (_data_dir() / "backups" / result["file"]).exists()


def test_scheduler_not_started_when_disabled(client):
    from app.config import get_settings

    assert get_settings().scheduler_enabled is False  # conftest env
    assert client.app.state.scheduler is None  # lifespan never built/started it
