"""M5 labels tests: tag normalization/allocation, resolve/claim/void lifecycle,
asset-tag assignment branches, entity-delete release, FTS sync, batch PDFs and
the pure label_positions layout math."""

import re

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


def _entity(client, auth, name, kind="space", parent_id=None, **extra):
    resp = client.post(
        f"{API}/entities",
        json={"name": name, "kind": kind, "parent_id": parent_id, **extra},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _inbox_id(client, auth):
    rows = client.get(f"{API}/entities/tree", headers=auth).json()
    return next(e["id"] for e in rows if e["protected"])


def _template_id(client, auth, name_part="L7160"):
    rows = client.get(f"{API}/labels/templates", headers=auth).json()
    return next(t["id"] for t in rows if name_part in t["name"])


def _batch(client, auth, **payload):
    resp = client.post(f"{API}/labels/batches", json=payload, headers=auth)
    assert resp.status_code == 201, resp.text
    return resp.json()

def _new_labels(client, auth, n=1):
    """A fresh mode-1 batch; returns its n unclaimed tags."""
    batch = _batch(client, auth, template_id=_template_id(client, auth), count=n)
    return [row["asset_tag"] for row in batch["labels"]]


def _resolve(client, auth, tag):
    return client.get(f"{API}/labels/resolve/{tag}", headers=auth)


def _claim(client, auth, tag, payload):
    return client.post(f"{API}/labels/{tag}/claim", json=payload, headers=auth)


def _assign(client, auth, entity_id, payload):
    return client.post(f"{API}/entities/{entity_id}/asset-tag", json=payload, headers=auth)


def _batch_detail(client, auth, batch_id):
    resp = client.get(f"{API}/labels/batches/{batch_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _tag_num(tag):
    return int(tag.split("-", 1)[1])


def _seeded_templates():
    from app.database import get_sessionmaker
    from app.models.labels import LabelTemplate
    from sqlalchemy import select

    with get_sessionmaker()() as db:
        rows = list(db.scalars(select(LabelTemplate).order_by(LabelTemplate.id)))
        for row in rows:
            db.expunge(row)
        return rows


# --- normalization & allocation -----------------------------------------------


def test_normalize_tag():
    from app.services.labels import normalize_tag

    assert normalize_tag(" a-0001 ") == "A-0001"
    assert normalize_tag("A-0001") == "A-0001"
    assert normalize_tag("\twidget-9x\n") == "WIDGET-9X"


def test_allocation_sequential_batches_never_overlap(client):  # client runs migrations
    from app.database import get_sessionmaker
    from app.services.labels import allocate_tags, format_tag

    with get_sessionmaker()() as db:
        first = allocate_tags(db, "A", 3)
        db.commit()
        second = allocate_tags(db, "A", 2)
        db.commit()
        third = allocate_tags(db, "A", 4)
        db.commit()

    assert len(first) == 3 and len(second) == 2 and len(third) == 4
    numbers = [_tag_num(t) for t in first + second + third]
    assert len(set(numbers)) == 9  # no overlap
    # RETURNING math: each batch is internally consecutive and continues the last.
    assert numbers == list(range(numbers[0], numbers[0] + 9))
    assert first[0] == format_tag("A", numbers[0])
    assert re.fullmatch(r"A-\d{4,}", first[0])


def test_format_tag_zero_pad_and_growth():
    from app.services.labels import format_tag

    assert format_tag("A", 7) == "A-0007"
    assert format_tag("A", 9999) == "A-9999"
    assert format_tag("A", 10000) == "A-10000"  # natural growth past 9999


# --- resolve ------------------------------------------------------------------


def test_resolve_unclaimed_and_case_insensitive(client, auth):
    (tag,) = _new_labels(client, auth)
    for variant in (tag, tag.lower(), f" {tag.lower()} "):
        resp = _resolve(client, auth, variant)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "unclaimed"
        assert body["label"]["asset_tag"] == tag
        assert "batch_id" in body["label"]


def test_resolve_entity(client, auth):
    (tag,) = _new_labels(client, auth)
    e = _entity(client, auth, "Resolve Target")
    assert _claim(client, auth, tag, {"entity_id": e["id"]}).status_code == 200
    body = _resolve(client, auth, tag.lower()).json()
    assert body["status"] == "entity"
    assert body["entity"]["id"] == e["id"]
    assert body["entity"]["asset_tag"] == tag
    assert "label" not in body  # exact union shape


def test_resolve_unknown_404(client, auth):
    resp = _resolve(client, auth, "A-999999")
    assert resp.status_code == 404
    assert "status" not in resp.json()


def test_resolve_requires_auth(client):
    assert client.get(f"{API}/labels/resolve/A-0001").status_code == 401


# --- claim --------------------------------------------------------------------


def test_claim_existing_entity(client, auth):
    (tag,) = _new_labels(client, auth)
    e = _entity(client, auth, "Claim Target")
    resp = _claim(client, auth, f" {tag.lower()} ", {"entity_id": e["id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_tag"] == tag  # normalized


def test_claim_create_variant(client, auth):
    (tag,) = _new_labels(client, auth)
    root = _entity(client, auth, "Claim Create Root")
    resp = _claim(
        client, auth, tag,
        {"create": {"name": "Claimed Box", "kind": "container", "parent_id": root["id"]}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["asset_tag"] == tag
    assert body["parent_id"] == root["id"]
    assert body["kind"] == "container"


def test_claim_create_containment_violation_rolls_back(client, auth):
    (tag,) = _new_labels(client, auth)
    # An item at root level violates containment -> 409, label stays unclaimed,
    # and no orphan entity is left behind.
    resp = _claim(
        client, auth, tag,
        {"create": {"name": "Orphan Probe Zx", "kind": "item", "parent_id": None}},
    )
    assert resp.status_code == 409, resp.text
    assert _resolve(client, auth, tag).json()["status"] == "unclaimed"
    tree_names = [e["name"] for e in client.get(f"{API}/entities/tree", headers=auth).json()]
    assert "Orphan Probe Zx" not in tree_names


def test_claim_409_already_claimed(client, auth):
    (tag,) = _new_labels(client, auth)
    e1 = _entity(client, auth, "First Claimer")
    e2 = _entity(client, auth, "Second Claimer")
    assert _claim(client, auth, tag, {"entity_id": e1["id"]}).status_code == 200
    assert _claim(client, auth, tag, {"entity_id": e2["id"]}).status_code == 409


def test_claim_409_entity_already_tagged(client, auth):
    tag1, tag2 = _new_labels(client, auth, 2)
    e = _entity(client, auth, "Twice Tagged")
    assert _claim(client, auth, tag1, {"entity_id": e["id"]}).status_code == 200
    assert _claim(client, auth, tag2, {"entity_id": e["id"]}).status_code == 409


def test_claim_409_inbox(client, auth):
    (tag,) = _new_labels(client, auth)
    assert _claim(client, auth, tag, {"entity_id": _inbox_id(client, auth)}).status_code == 409
    assert _resolve(client, auth, tag).json()["status"] == "unclaimed"


def test_claim_unknown_tag_404_and_payload_validation(client, auth):
    assert _claim(client, auth, "A-999999", {"entity_id": 1}).status_code == 404
    (tag,) = _new_labels(client, auth)
    assert _claim(client, auth, tag, {}).status_code == 422  # neither variant
    e = _entity(client, auth, "Both Variant Probe")
    assert _claim(
        client, auth, tag,
        {"entity_id": e["id"], "create": {"name": "X", "kind": "space"}},
    ).status_code == 422  # both variants


# --- void ---------------------------------------------------------------------


def test_void_transitions(client, auth):
    (tag,) = _new_labels(client, auth)
    resp = client.post(f"{API}/labels/{tag.lower()}/void", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "void"
    assert resp.json()["asset_tag"] == tag
    # void -> void is a 409; a voided label cannot be claimed and never resolves.
    assert client.post(f"{API}/labels/{tag}/void", headers=auth).status_code == 409
    e = _entity(client, auth, "Void Probe")
    assert _claim(client, auth, tag, {"entity_id": e["id"]}).status_code == 409
    assert _resolve(client, auth, tag).status_code == 404


def test_void_claimed_409(client, auth):
    (tag,) = _new_labels(client, auth)
    e = _entity(client, auth, "Void Claimed Probe")
    assert _claim(client, auth, tag, {"entity_id": e["id"]}).status_code == 200
    assert client.post(f"{API}/labels/{tag}/void", headers=auth).status_code == 409


# --- asset-tag assignment -----------------------------------------------------


def test_assign_auto_allocates_monotonic_tags(client, auth):
    e1 = _entity(client, auth, "Auto Tag One")
    e2 = _entity(client, auth, "Auto Tag Two")
    tag1 = _assign(client, auth, e1["id"], {"auto": True}).json()["asset_tag"]
    tag2 = _assign(client, auth, e2["id"], {"auto": True}).json()["asset_tag"]
    assert re.fullmatch(r"A-\d{4,}", tag1)
    assert re.fullmatch(r"A-\d{4,}", tag2)
    assert _tag_num(tag2) > _tag_num(tag1)


def test_assign_custom_freeform_normalized(client, auth):
    e = _entity(client, auth, "Custom Tag Holder")
    resp = _assign(client, auth, e["id"], {"tag": " shelf-b12 "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_tag"] == "SHELF-B12"


def test_assign_custom_matching_unclaimed_label_claims_it(client, auth):
    batch = _batch(client, auth, template_id=_template_id(client, auth), count=1)
    tag = batch["labels"][0]["asset_tag"]
    e = _entity(client, auth, "Assign Claims Sticker")
    resp = _assign(client, auth, e["id"], {"tag": tag.lower()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_tag"] == tag
    row = _batch_detail(client, auth, batch["id"])["labels"][0]
    assert row["status"] == "claimed"
    assert row["entity_id"] == e["id"]
    assert row["claimed_at"] is not None


def test_assign_custom_collisions_409(client, auth):
    (claimed_tag,) = _new_labels(client, auth)
    owner = _entity(client, auth, "Collision Owner")
    assert _claim(client, auth, claimed_tag, {"entity_id": owner["id"]}).status_code == 200
    other = _entity(client, auth, "Collision Prober")
    # Another entity's tag (also a claimed label) -> 409.
    assert _assign(client, auth, other["id"], {"tag": claimed_tag}).status_code == 409
    # A voided label's tag -> 409.
    (void_tag,) = _new_labels(client, auth)
    assert client.post(f"{API}/labels/{void_tag}/void", headers=auth).status_code == 200
    assert _assign(client, auth, other["id"], {"tag": void_tag}).status_code == 409
    # Free-form tag squatted by another entity -> 409 (case-insensitive).
    a = _entity(client, auth, "Freeform A")
    b = _entity(client, auth, "Freeform B")
    assert _assign(client, auth, a["id"], {"tag": "UNIQ-FREE-1"}).status_code == 200
    assert _assign(client, auth, b["id"], {"tag": "uniq-free-1"}).status_code == 409


def test_assign_null_clears_and_reverts_label(client, auth):
    batch = _batch(client, auth, template_id=_template_id(client, auth), count=1)
    tag = batch["labels"][0]["asset_tag"]
    e = _entity(client, auth, "Clear Me")
    assert _claim(client, auth, tag, {"entity_id": e["id"]}).status_code == 200
    resp = _assign(client, auth, e["id"], {"tag": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_tag"] is None
    row = _batch_detail(client, auth, batch["id"])["labels"][0]
    assert row["status"] == "unclaimed"
    assert row["entity_id"] is None
    assert row["claimed_at"] is None
    # The released sticker can be re-bound.
    e2 = _entity(client, auth, "Rebinder")
    assert _claim(client, auth, tag, {"entity_id": e2["id"]}).status_code == 200


def test_assign_inbox_409_and_empty_payload_422(client, auth):
    assert _assign(client, auth, _inbox_id(client, auth), {"auto": True}).status_code == 409
    e = _entity(client, auth, "Payload Probe")
    assert _assign(client, auth, e["id"], {}).status_code == 422  # no explicit choice
    assert _assign(client, auth, e["id"], {"auto": True, "tag": "X-1"}).status_code == 422


def test_entity_delete_reverts_claimed_label(client, auth):
    batch = _batch(client, auth, template_id=_template_id(client, auth), count=1)
    tag = batch["labels"][0]["asset_tag"]
    e = _entity(client, auth, "Doomed Holder")
    assert _claim(client, auth, tag, {"entity_id": e["id"]}).status_code == 200
    assert client.delete(f"{API}/entities/{e['id']}", headers=auth).status_code == 204
    row = _batch_detail(client, auth, batch["id"])["labels"][0]
    assert row["status"] == "unclaimed"
    assert row["entity_id"] is None
    assert _resolve(client, auth, tag).json()["status"] == "unclaimed"


def test_search_finds_entity_by_asset_tag_after_assign(client, auth):
    e = _entity(client, auth, "Fts Tag Holder")
    assert _assign(client, auth, e["id"], {"tag": "QWXY-4242"}).status_code == 200
    results = client.get(f"{API}/search", params={"q": "qwxy"}, headers=auth).json()["results"]
    assert e["id"] in [r["id"] for r in results]
    # Clearing removes it from the index again (entity AU trigger).
    assert _assign(client, auth, e["id"], {"tag": None}).status_code == 200
    results = client.get(f"{API}/search", params={"q": "qwxy"}, headers=auth).json()["results"]
    assert e["id"] not in [r["id"] for r in results]


# --- batches ------------------------------------------------------------------


def _pdf_bytes(client, auth, batch_id):
    resp = client.get(f"{API}/labels/batches/{batch_id}/pdf", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    return resp.content


def test_batch_mode1_rows_and_pdf(client, auth):
    template_id = _template_id(client, auth)
    batch = _batch(client, auth, template_id=template_id, count=5, note="shelf run")
    assert batch["note"] == "shelf run"
    assert batch["label_count"] == 5
    assert batch["pdf_url"] == f"{API}/labels/batches/{batch['id']}/pdf"
    assert batch["template"]["id"] == template_id
    assert len(batch["labels"]) == 5
    numbers = [_tag_num(row["asset_tag"]) for row in batch["labels"]]
    assert numbers == list(range(numbers[0], numbers[0] + 5))  # consecutive
    for row in batch["labels"]:
        assert row["status"] == "unclaimed"
        assert row["entity_id"] is None
        assert row["claimed_at"] is None
    # PDF exists on disk under data_dir/labels and is a real PDF.
    from app.config import get_settings

    pdf_path = get_settings().data_dir / "labels" / f"batch-{batch['id']:04d}.pdf"
    assert pdf_path.is_file()
    assert _pdf_bytes(client, auth, batch["id"]).startswith(b"%PDF-")


def test_batch_pdf_requires_auth(client, auth):
    batch = _batch(client, auth, template_id=_template_id(client, auth), count=1)
    assert client.get(f"{API}/labels/batches/{batch['id']}/pdf").status_code == 401


def test_batch_skip_first_shifts_positions(client, auth):
    from app.services.labelpdf import label_positions

    template = _seeded_templates()[0]
    plain = label_positions(template, 5)
    shifted = label_positions(template, 5, skip_first=2)
    assert shifted[0] == label_positions(template, 7)[2]
    assert shifted[0] != plain[0]
    # API accepts it and still creates exactly `count` labels.
    batch = _batch(
        client, auth, template_id=_template_id(client, auth), count=2, skip_first=3
    )
    assert batch["label_count"] == 2


def test_batch_multipage_when_count_exceeds_capacity(client, auth):
    from app.services.labelpdf import label_positions

    # L7165 holds 2x4 = 8 per sheet; 10 labels span two pages.
    template_id = _template_id(client, auth, "L7165")
    batch = _batch(client, auth, template_id=template_id, count=10)
    assert batch["label_count"] == 10
    template = next(t for t in _seeded_templates() if t.id == template_id)
    positions = label_positions(template, 10)
    assert positions[7][0] == 0 and positions[8][0] == 1  # page break after 8
    assert positions[8][1:3] == (0, 0)  # page 2 restarts top-left
    assert _pdf_bytes(client, auth, batch["id"]).startswith(b"%PDF-")


def test_batch_mode2_entities(client, auth):
    tagged = _entity(client, auth, "Pre Tagged For Batch")
    pre_tag = _assign(client, auth, tagged["id"], {"auto": True}).json()["asset_tag"]
    untagged = _entity(client, auth, "Untagged For Batch")
    long_name = _entity(client, auth, "Very " * 60 + "Long Named Cabinet")  # ellipsized, no crash
    batch = _batch(
        client, auth,
        template_id=_template_id(client, auth),
        entity_ids=[tagged["id"], untagged["id"], long_name["id"]],
    )
    assert batch["label_count"] == 3
    by_entity = {row["entity_id"]: row for row in batch["labels"]}
    assert by_entity[tagged["id"]]["asset_tag"] == pre_tag
    for row in batch["labels"]:
        assert row["status"] == "claimed"
        assert row["claimed_at"] is not None
        assert row["entity_name"]
    # The untagged entity got a real tag persisted on the entity itself.
    new_tag = by_entity[untagged["id"]]["asset_tag"]
    assert re.fullmatch(r"A-\d{4,}", new_tag)
    resp = client.get(f"{API}/entities/{untagged['id']}", headers=auth)
    assert resp.json()["asset_tag"] == new_tag
    assert _pdf_bytes(client, auth, batch["id"]).startswith(b"%PDF-")


def test_batch_mode2_inbox_409(client, auth):
    resp = client.post(
        f"{API}/labels/batches",
        json={"template_id": _template_id(client, auth), "entity_ids": [_inbox_id(client, auth)]},
        headers=auth,
    )
    assert resp.status_code == 409


def test_batch_payload_validation(client, auth):
    template_id = _template_id(client, auth)
    bad = [
        {"template_id": template_id},  # neither mode
        {"template_id": template_id, "count": 2, "entity_ids": [1]},  # both modes
        {"template_id": template_id, "count": 0},  # count < 1
        {"template_id": template_id, "entity_ids": []},  # empty list
        {"template_id": template_id, "count": 1, "skip_first": -1},
    ]
    for payload in bad:
        assert client.post(f"{API}/labels/batches", json=payload, headers=auth).status_code == 422
    assert client.post(
        f"{API}/labels/batches", json={"template_id": 999999, "count": 1}, headers=auth
    ).status_code == 404


def test_batch_listing_with_status_counts(client, auth):
    batch = _batch(client, auth, template_id=_template_id(client, auth), count=3, note="mixed")
    tags = [row["asset_tag"] for row in batch["labels"]]
    e = _entity(client, auth, "Listing Claimer")
    assert _claim(client, auth, tags[0], {"entity_id": e["id"]}).status_code == 200
    assert client.post(f"{API}/labels/{tags[1]}/void", headers=auth).status_code == 200

    rows = client.get(f"{API}/labels/batches", headers=auth).json()
    row = next(r for r in rows if r["id"] == batch["id"])
    assert row["counts"] == {"unclaimed": 1, "claimed": 1, "void": 1}
    assert row["label_count"] == 3
    assert row["template"]["id"] == batch["template"]["id"]

    detail = _batch_detail(client, auth, batch["id"])
    by_tag = {r["asset_tag"]: r for r in detail["labels"]}
    assert by_tag[tags[0]]["status"] == "claimed"
    assert by_tag[tags[0]]["entity_name"] == "Listing Claimer"
    assert by_tag[tags[1]]["status"] == "void"
    assert by_tag[tags[2]]["status"] == "unclaimed"


def test_batch_detail_404(client, auth):
    assert client.get(f"{API}/labels/batches/999999", headers=auth).status_code == 404
    assert client.get(f"{API}/labels/batches/999999/pdf", headers=auth).status_code == 404


def test_labels_config_exposes_base_url(client, auth):
    resp = client.get(f"{API}/labels/config", headers=auth)
    assert resp.status_code == 200
    base_url = resp.json()["base_url"]
    assert base_url.startswith("http")
    assert not base_url.endswith("/")


# --- label_positions layout math (pure, all 3 seeded templates) ---------------


def test_label_positions_all_seeded_templates(client):  # client runs migrations
    from app.services.labelpdf import label_positions

    templates = _seeded_templates()
    assert len(templates) == 3
    for template in templates:
        per_page = template.cols * template.rows
        positions = label_positions(template, per_page + 3)

        # First label sits exactly at the margins.
        assert positions[0] == (0, 0, 0, template.margin_left_mm, template.margin_top_mm)

        # Second label steps one pitch right (pitch = label + gutter).
        assert positions[1][3] == pytest.approx(
            template.margin_left_mm + template.label_w_mm + template.gutter_x_mm
        )
        assert positions[1][4] == template.margin_top_mm

        # Last label of page 1 is the bottom-right slot and stays inside A4.
        last = positions[per_page - 1]
        assert last[0] == 0
        assert last[1] == template.cols - 1 and last[2] == template.rows - 1
        assert last[3] + template.label_w_mm <= template.page_w_mm + 1e-6
        assert last[4] + template.label_h_mm <= template.page_h_mm + 1e-6

        # count/pages arithmetic: slot per_page wraps to page 1 top-left.
        assert positions[per_page] == (1, 0, 0, template.margin_left_mm, template.margin_top_mm)
        assert len(positions) == per_page + 3

        # skip_first shifts print order without moving the grid.
        assert label_positions(template, 1, skip_first=4)[0] == positions[4]
        assert label_positions(template, 2, skip_first=per_page - 1)[1][0] == 1  # spills to page 2


# --- M5 hardening (adversarial-review regressions) ----------------------------


def test_stale_claim_of_second_tag_conflicts_cleanly(client, auth):
    """Race backstop: binding a tag to an entity whose asset_tag changed since it
    was read must 409 and leave the label unclaimed (guarded UPDATE, not
    read-then-write). Emulated by pre-tagging the entity via the ORM after the
    label was printed."""
    from app.database import get_sessionmaker
    from app.models.entity import Entity as E

    tag = _new_labels(client, auth)[0]
    entity = _entity(client, auth, "RaceTarget", "item", parent_id=_entity(client, auth, "RaceRoot")["id"])
    with get_sessionmaker()() as db:
        db.query(E).filter(E.id == entity["id"]).update({"asset_tag": "RACE-9999"})
        db.commit()

    resp = _claim(client, auth, tag, {"entity_id": entity["id"]})
    assert resp.status_code == 409
    assert _resolve(client, auth, tag).json()["status"] == "unclaimed"


def test_orphaned_claimed_label_can_be_voided(client, auth):
    """Repair path: a 'claimed' label no entity carries (historical race damage)
    must be voidable instead of stuck forever."""
    from app.database import get_sessionmaker
    from app.models.labels import PrintedLabel

    tag = _new_labels(client, auth)[0]
    with get_sessionmaker()() as db:
        db.query(PrintedLabel).filter(PrintedLabel.asset_tag == tag).update(
            {"status": "claimed", "entity_id": None}
        )
        db.commit()

    resp = client.post(f"{API}/labels/{tag}/void", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "void"


def test_void_refused_while_entity_carries_tag(client, auth):
    tag = _new_labels(client, auth)[0]
    root = _entity(client, auth, "VoidRoot")
    item = _entity(client, auth, "VoidItem", "item", parent_id=root["id"])
    assert _claim(client, auth, tag, {"entity_id": item["id"]}).status_code == 200
    resp = client.post(f"{API}/labels/{tag}/void", headers=auth)
    assert resp.status_code == 409


def test_mode2_reprint_counts_include_foreign_batch_labels(client, auth):
    """A mode-2 batch reprinting a tag tracked by an earlier batch must report
    the label in its response (it IS on the PDF)."""
    root = _entity(client, auth, "ReprintRoot")
    a = _entity(client, auth, "ReprintA", "item", parent_id=root["id"])
    b = _entity(client, auth, "ReprintB", "item", parent_id=root["id"])
    tid = _template_id(client, auth)

    first = _batch(client, auth, template_id=tid, entity_ids=[a["id"]])
    assert first["label_count"] == 1

    second = _batch(client, auth, template_id=tid, entity_ids=[a["id"], b["id"]])
    assert second["label_count"] == 2, "reprint of A's label must be reported"
    tags = {row["asset_tag"] for row in second["labels"]}
    assert len(tags) == 2


def test_skip_first_bounded_by_sheet_capacity(client, auth):
    tid = _template_id(client, auth)  # L7160: 3x7 = 21 per sheet
    resp = client.post(
        f"{API}/labels/batches",
        json={"template_id": tid, "count": 1, "skip_first": 21},
        headers=auth,
    )
    assert resp.status_code == 409
    ok = _batch(client, auth, template_id=tid, count=1, skip_first=20)
    assert ok["label_count"] == 1


def test_labels_config_base_url_trailing_slash_stripped(client, auth):
    from app.database import get_sessionmaker
    from app.models.meta import Meta

    with get_sessionmaker()() as db:
        row = db.get(Meta, "base_url")
        original = row.value
        row.value = "https://example.tailnet.ts.net/"
        db.commit()
    try:
        cfg = client.get(f"{API}/labels/config", headers=auth).json()
        assert cfg["base_url"] == "https://example.tailnet.ts.net"
    finally:
        with get_sessionmaker()() as db:
            db.get(Meta, "base_url").value = original
            db.commit()


def test_assign_and_claim_to_archived_entity_allowed(client, auth):
    """Pinned behavior: archived entities can still be tagged — stickers on
    boxes in deep storage are the normal case, not an error."""
    root = _entity(client, auth, "ArcTagRoot")
    item = _entity(client, auth, "ArcTagItem", "item", parent_id=root["id"])
    client.post(f"{API}/entities/{item['id']}/archive", headers=auth)

    resp = _assign(client, auth, item["id"], {"auto": True})
    assert resp.status_code == 200
    assert resp.json()["asset_tag"]
