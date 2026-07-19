"""Inventory service (M6): quantity adjustment, low-stock, valuation, recent.

Archived-subtree visibility reuses tree.not_in_archived_subtree() — the single
shared predicate — so these listings can never disagree with /tree and /search.
Domain errors reuse tree.NotFoundError (404); routers translate.
"""

from sqlalchemy import Integer, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.entity import Entity
from app.models.meta import Meta
from app.models.metadata import Category
from app.services import tree


def adjust_quantity(db: Session, entity_id: int, delta: float) -> Entity:
    """Add delta to the entity's quantity, flooring at 0. Allowed on ANY entity
    (quantity is just a number), consumable or not."""
    entity = tree.get_entity(db, entity_id)
    entity.quantity = max(0.0, (entity.quantity or 0.0) + delta)
    db.commit()
    return entity


def low_stock(db: Session) -> list[Entity]:
    """Consumables at/below their threshold, most-depleted first (quantity /
    threshold ratio ascending; a 0 threshold yields NULL which sorts first)."""
    ratio = Entity.quantity / Entity.low_stock_threshold
    stmt = (
        select(Entity)
        .where(
            Entity.is_consumable.is_(True),
            Entity.low_stock_threshold.is_not(None),
            Entity.quantity <= Entity.low_stock_threshold,
            tree.not_in_archived_subtree(),
        )
        .order_by(ratio, func.lower(Entity.name))
    )
    return list(db.scalars(stmt))


# Per-entity value: current_value ?? purchase_price ?? 0.
_VALUE = func.coalesce(Entity.current_value, Entity.purchase_price, 0.0)
_INSURED_VALUE = case((Entity.insured.is_(True), _VALUE), else_=0.0)

# Root id parsed from the path cache: '/12/34/' -> substr from 2 up to the next '/'.
_ROOT_ID = cast(
    func.substr(Entity.path, 2, func.instr(func.substr(Entity.path, 2), "/") - 1),
    Integer,
)


def valuation(db: Session) -> dict:
    """Totals plus per-root and per-category breakdowns. Excludes archived
    subtrees and sold items (sold_date set); groups ordered by total desc.

    Sums are numeric only: `currency` reports the instance default the totals
    are assumed to be in, and `mixed_currency_count` counts contributing
    (value-bearing) entities whose own currency is set and differs from it."""
    included = (Entity.sold_date.is_(None), tree.not_in_archived_subtree())

    default_currency = (
        db.scalar(select(Meta.value).where(Meta.key == "default_currency")) or "EUR"
    )
    mixed_currency_count = db.scalar(
        select(func.count(Entity.id)).where(
            *included,
            Entity.currency.is_not(None),
            Entity.currency != default_currency,
            or_(Entity.current_value.is_not(None), Entity.purchase_price.is_not(None)),
        )
    )

    total, insured_total = db.execute(
        select(
            func.coalesce(func.sum(_VALUE), 0.0),
            func.coalesce(func.sum(_INSURED_VALUE), 0.0),
        ).where(*included)
    ).one()

    root_rows = db.execute(
        select(_ROOT_ID, func.sum(_VALUE), func.sum(_INSURED_VALUE))
        .where(*included)
        .group_by(_ROOT_ID)
        .order_by(func.sum(_VALUE).desc())
    ).all()
    root_names = {
        entity_id: name
        for entity_id, name in db.execute(
            select(Entity.id, Entity.name).where(
                Entity.id.in_([row[0] for row in root_rows])
            )
        )
    }

    category_rows = db.execute(
        select(Entity.category_id, func.sum(_VALUE), func.sum(_INSURED_VALUE))
        .where(*included)
        .group_by(Entity.category_id)
        .order_by(func.sum(_VALUE).desc())
    ).all()
    category_names = {
        category_id: name
        for category_id, name in db.execute(
            select(Category.id, Category.name).where(
                Category.id.in_([row[0] for row in category_rows if row[0] is not None])
            )
        )
    }

    return {
        "total": total,
        "insured_total": insured_total,
        "currency": default_currency,
        "mixed_currency_count": mixed_currency_count,
        "by_root": [
            {
                "entity": {"id": root_id, "name": root_names.get(root_id, "?")},
                "total": root_total,
                "insured_total": root_insured,
            }
            for root_id, root_total, root_insured in root_rows
        ],
        "by_category": [
            {
                "category": (
                    None
                    if category_id is None
                    else {"id": category_id, "name": category_names.get(category_id, "?")}
                ),
                "total": cat_total,
                "insured_total": cat_insured,
            }
            for category_id, cat_total, cat_insured in category_rows
        ],
    }


def recent(db: Session, limit: int = 10) -> list[Entity]:
    """Most recently created non-archived entities (dashboard card)."""
    stmt = (
        select(Entity)
        .where(tree.not_in_archived_subtree())
        .order_by(Entity.created_at.desc(), Entity.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))
