"""M6 inventory tests: PATCH validation, quantity-adjust, low-stock, valuation,
recent. The DB is shared across the whole test session, so assertions on the
global endpoints (valuation, low-stock, recent) are scoped to this module's own
entities instead of exact global lists."""

import pytest

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


def _make(client, auth, name, kind, parent_id=None):
    resp = client.post(
        f"{API}/entities",
        json={"name": name, "kind": kind, "parent_id": parent_id},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _patch(client, auth, entity_id, payload, expect=200):
    resp = client.patch(f"{API}/entities/{entity_id}", json=payload, headers=auth)
    assert resp.status_code == expect, resp.text
    return resp.json()


# --- PATCH inventory fields ---------------------------------------------------


def test_patch_inventory_fields_roundtrip(client, auth):
    root = _make(client, auth, "InvRoot", "space")
    item = _make(client, auth, "InvItem", "item", root["id"])
    body = _patch(client, auth, item["id"], {
        "quantity": 3,
        "unit": "pcs",
        "is_consumable": True,
        "low_stock_threshold": 5,
        "purchase_date": "2025-06-01",
        "purchase_price": 19.99,
        "purchase_from": "Shop",
        "currency": "EUR",
        "current_value": 15,
        "insured": True,
        "warranty_expires": "2027-06-01",
        "warranty_lifetime": False,
        "warranty_notes": "2y standard",
        "serial_number": "SN-1",
        "model_number": "MN-1",
        "manufacturer": "Acme",
        "sold_to": "Nobody",
        "sold_notes": "n/a",
    })
    assert body["quantity"] == 3
    assert body["unit"] == "pcs"
    assert body["is_consumable"] is True
    assert body["low_stock_threshold"] == 5
    assert body["purchase_date"] == "2025-06-01"
    assert body["purchase_price"] == 19.99
    assert body["currency"] == "EUR"
    assert body["current_value"] == 15
    assert body["insured"] is True
    assert body["warranty_expires"] == "2027-06-01"
    assert body["serial_number"] == "SN-1"
    assert body["manufacturer"] == "Acme"
    # GET returns the same values (persisted, not just echoed).
    got = client.get(f"{API}/entities/{item['id']}", headers=auth).json()
    assert got["purchase_price"] == 19.99
    assert got["is_consumable"] is True


def test_patch_null_clears_nullable_fields(client, auth):
    root = _make(client, auth, "InvClear", "space")
    item = _make(client, auth, "InvClearItem", "item", root["id"])
    _patch(client, auth, item["id"], {
        "low_stock_threshold": 4, "purchase_date": "2025-01-02",
        "currency": "USD", "unit": "kg",
    })
    body = _patch(client, auth, item["id"], {
        "low_stock_threshold": None, "purchase_date": None,
        "currency": None, "unit": None,
    })
    assert body["low_stock_threshold"] is None
    assert body["purchase_date"] is None
    assert body["currency"] is None
    assert body["unit"] is None


@pytest.mark.parametrize("payload", [
    {"purchase_date": "not-a-date"},
    {"purchase_date": "2025-13-01"},
    {"purchase_date": "20250101"},
    {"warranty_expires": "01/02/2025"},
    {"sold_date": "2025-2-1"},
    {"purchase_price": -1},
    {"current_value": -0.5},
    {"sold_price": -3},
    {"quantity": -1},
    {"low_stock_threshold": -2},
    {"currency": "eur"},
    {"currency": "EURO"},
    {"currency": "E1R"},
    {"quantity": None},
    {"is_consumable": None},
    {"insured": None},
    {"warranty_lifetime": None},
])
def test_patch_inventory_validation_422(client, auth, payload):
    root = _make(client, auth, f"InvVal-{list(payload)[0]}-{list(payload.values())[0]}", "space")
    resp = client.patch(f"{API}/entities/{root['id']}", json=payload, headers=auth)
    assert resp.status_code == 422, resp.text


# --- quantity-adjust ----------------------------------------------------------


def test_quantity_adjust_and_floor(client, auth):
    root = _make(client, auth, "QtyRoot", "space")
    item = _make(client, auth, "QtyItem", "item", root["id"])
    assert item["quantity"] == 1

    resp = client.post(
        f"{API}/entities/{item['id']}/quantity-adjust", json={"delta": 2.5}, headers=auth
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity"] == 3.5

    resp = client.post(
        f"{API}/entities/{item['id']}/quantity-adjust", json={"delta": -100}, headers=auth
    )
    assert resp.json()["quantity"] == 0  # floors at 0, no error

    # Allowed on non-consumables and non-items alike — it is just a number.
    resp = client.post(
        f"{API}/entities/{root['id']}/quantity-adjust", json={"delta": 1}, headers=auth
    )
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 2

    missing = client.post(
        f"{API}/entities/999999/quantity-adjust", json={"delta": 1}, headers=auth
    )
    assert missing.status_code == 404


def test_quantity_adjust_requires_auth(client):
    assert client.post(f"{API}/entities/1/quantity-adjust", json={"delta": 1}).status_code == 401


# --- low stock ----------------------------------------------------------------


def test_low_stock_filtering_order_and_archived_exclusion(client, auth):
    root = _make(client, auth, "StockRoot", "space")
    box = _make(client, auth, "StockBox", "container", root["id"])

    def consumable(name, qty, threshold, parent=None):
        e = _make(client, auth, name, "item", parent or root["id"])
        _patch(client, auth, e["id"], {
            "quantity": qty, "is_consumable": True, "low_stock_threshold": threshold,
        })
        return e

    nearly_out = consumable("StockNearlyOut", 1, 10)   # ratio 0.1
    halfway = consumable("StockHalfway", 5, 10)        # ratio 0.5
    at_limit = consumable("StockAtLimit", 10, 10)      # ratio 1.0
    hidden = consumable("StockHidden", 0, 5, parent=box["id"])  # archived away below

    plenty = consumable("StockPlenty", 20, 10)  # above threshold — excluded
    no_threshold = _make(client, auth, "StockNoThr", "item", root["id"])
    _patch(client, auth, no_threshold["id"], {"quantity": 0, "is_consumable": True})
    not_consumable = _make(client, auth, "StockNotCons", "item", root["id"])
    _patch(client, auth, not_consumable["id"], {"quantity": 0, "low_stock_threshold": 5})

    assert client.post(f"{API}/entities/{box['id']}/archive", headers=auth).status_code == 200

    rows = client.get(f"{API}/inventory/low-stock", headers=auth)
    assert rows.status_code == 200, rows.text
    ids = [e["id"] for e in rows.json()]

    for e in (nearly_out, halfway, at_limit):
        assert e["id"] in ids
    for e in (plenty, no_threshold, not_consumable, hidden):
        assert e["id"] not in ids
    # Ratio ascending: our three appear most-depleted first.
    ours = [i for i in ids if i in {nearly_out["id"], halfway["id"], at_limit["id"]}]
    assert ours == [nearly_out["id"], halfway["id"], at_limit["id"]]


def test_low_stock_zero_threshold_appears_and_sorts_first(client, auth):
    # Documented semantic: a 0 threshold divides to a NULL ratio, which SQLite
    # sorts BEFORE every numeric ratio — the row appears, first in the list.
    root = _make(client, auth, "StockZeroRoot", "space")
    zero = _make(client, auth, "StockZero", "item", root["id"])
    _patch(client, auth, zero["id"], {
        "quantity": 0, "is_consumable": True, "low_stock_threshold": 0,
    })
    other = _make(client, auth, "StockZeroOther", "item", root["id"])
    _patch(client, auth, other["id"], {
        "quantity": 1, "is_consumable": True, "low_stock_threshold": 10,
    })

    rows = client.get(f"{API}/inventory/low-stock", headers=auth)
    assert rows.status_code == 200, rows.text
    ids = [e["id"] for e in rows.json()]
    assert zero["id"] in ids
    assert other["id"] in ids
    assert ids[0] == zero["id"]  # NULL ratio sorts before all numeric ratios


# --- valuation ----------------------------------------------------------------


def test_valuation_math_exclusions_and_fallback(client, auth):
    root = _make(client, auth, "ValRoot", "space")

    def valued(name, **fields):
        e = _make(client, auth, name, "item", root["id"])
        _patch(client, auth, e["id"], fields)
        return e

    valued("ValCurrent", current_value=100, insured=True)         # 100 (insured)
    valued("ValFallback", purchase_price=40)                      # 40 (purchase fallback)
    valued("ValBoth", purchase_price=99, current_value=10)        # 10 (current wins)
    valued("ValNone")                                             # 0
    valued("ValSold", current_value=500, sold_date="2025-01-01")  # excluded (sold)
    archived = valued("ValArchived", current_value=300)
    client.post(f"{API}/entities/{archived['id']}/archive", headers=auth)

    resp = client.get(f"{API}/inventory/valuation", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "total", "insured_total", "currency", "mixed_currency_count",
        "by_root", "by_category",
    }

    mine = next(r for r in body["by_root"] if r["entity"]["id"] == root["id"])
    assert mine["entity"]["name"] == "ValRoot"
    assert mine["total"] == 150  # 100 + 40 + 10 (+0), sold + archived excluded
    assert mine["insured_total"] == 100
    # Global totals are consistent aggregates of the breakdown.
    assert body["total"] == pytest.approx(sum(r["total"] for r in body["by_root"]))
    assert body["insured_total"] == pytest.approx(
        sum(r["insured_total"] for r in body["by_root"])
    )
    assert body["total"] >= mine["total"]


def test_valuation_by_category(client, auth):
    resp = client.post(
        f"{API}/categories", json={"name": "ValuationCat"}, headers=auth
    )
    assert resp.status_code == 201, resp.text
    category = resp.json()

    root = _make(client, auth, "ValCatRoot", "space")
    item = _make(client, auth, "ValCatItem", "item", root["id"])
    _patch(client, auth, item["id"], {"current_value": 77, "insured": True})
    _patch(client, auth, item["id"], {"category_id": category["id"]})

    body = client.get(f"{API}/inventory/valuation", headers=auth).json()
    mine = next(
        c for c in body["by_category"]
        if c["category"] is not None and c["category"]["id"] == category["id"]
    )
    assert mine["category"]["name"] == "ValuationCat"
    assert mine["total"] == 77
    assert mine["insured_total"] == 77
    # The uncategorized bucket exists as category: null.
    assert any(c["category"] is None for c in body["by_category"])


def test_valuation_currency_and_mixed_count(client, auth):
    body = client.get(f"{API}/inventory/valuation", headers=auth).json()
    assert body["currency"] == "EUR"  # seeded meta default_currency
    base = body["mixed_currency_count"]

    root = _make(client, auth, "ValCurRoot", "space")
    item = _make(client, auth, "ValCurItem", "item", root["id"])
    _patch(client, auth, item["id"], {"current_value": 5, "currency": "USD"})
    # A currency without any value does NOT count — nothing of it is summed.
    valueless = _make(client, auth, "ValCurValueless", "item", root["id"])
    _patch(client, auth, valueless["id"], {"currency": "USD"})
    # The default currency never counts as mixed.
    default = _make(client, auth, "ValCurDefault", "item", root["id"])
    _patch(client, auth, default["id"], {"current_value": 7, "currency": "EUR"})

    body = client.get(f"{API}/inventory/valuation", headers=auth).json()
    assert body["mixed_currency_count"] == base + 1


def test_patch_sold_date_null_returns_entity_to_valuation(client, auth):
    root = _make(client, auth, "SoldClearRoot", "space")
    item = _make(client, auth, "SoldClearItem", "item", root["id"])
    _patch(client, auth, item["id"], {"current_value": 55, "sold_date": "2025-05-05"})

    body = client.get(f"{API}/inventory/valuation", headers=auth).json()
    mine = next(r for r in body["by_root"] if r["entity"]["id"] == root["id"])
    assert mine["total"] == 0  # sold — excluded

    cleared = _patch(client, auth, item["id"], {"sold_date": None})
    assert cleared["sold_date"] is None
    body = client.get(f"{API}/inventory/valuation", headers=auth).json()
    mine = next(r for r in body["by_root"] if r["entity"]["id"] == root["id"])
    assert mine["total"] == 55  # back in the sums


# --- recent -------------------------------------------------------------------


def test_recent_returns_newest_first_excluding_archived(client, auth):
    root = _make(client, auth, "RecentRoot", "space")
    a = _make(client, auth, "RecentA", "item", root["id"])
    b = _make(client, auth, "RecentB", "item", root["id"])
    c = _make(client, auth, "RecentC", "item", root["id"])
    client.post(f"{API}/entities/{b['id']}/archive", headers=auth)

    rows = client.get(f"{API}/inventory/recent", headers=auth)
    assert rows.status_code == 200, rows.text
    listing = rows.json()
    assert len(listing) <= 10
    ids = [e["id"] for e in listing]
    assert ids[0] == c["id"]  # newest first
    assert a["id"] in ids
    assert b["id"] not in ids  # archived hidden
    # Newest-first among our own entities.
    assert ids.index(c["id"]) < ids.index(a["id"])


def test_inventory_endpoints_require_auth(client):
    assert client.get(f"{API}/inventory/low-stock").status_code == 401
    assert client.get(f"{API}/inventory/valuation").status_code == 401
    assert client.get(f"{API}/inventory/recent").status_code == 401
