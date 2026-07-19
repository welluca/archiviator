"""M4 metadata + search: tag/category/field/preset tables, entity.category_id,
FTS5 search index with maintenance triggers, backfill of existing entities.

Order matters: entity.category_id is added via batch_alter_table BEFORE the
entity triggers exist — the batch recreate drops the old entity table, which
would silently drop any triggers already attached to it. The FTS table and all
triggers therefore come last, followed by the backfill of live rows (the real
DB already contains entities; the metadata tables are empty at this point, so
the backfilled tags/fields columns start blank).

Trigger SQL is mirrored by app.services.search.rebuild_search — keep in sync.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-19

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


# Recompute snippets used by the triggers ({entity} is new.X/old.X per trigger).
_TAGS_FOR = (
    "SELECT COALESCE(group_concat(t.name, ' '), '') FROM entity_tag et "
    "JOIN tag t ON t.id = et.tag_id WHERE et.entity_id = {entity}"
)
_FIELDS_FOR = (
    "SELECT COALESCE(group_concat(fd.name || ' ' || fv.value_text, ' '), '') "
    "FROM field_value fv JOIN field_def fd ON fd.id = fv.field_def_id "
    "WHERE fv.entity_id = {entity}"
)

TRIGGERS: dict[str, str] = {
    "search_fts_entity_ai": """
        CREATE TRIGGER search_fts_entity_ai AFTER INSERT ON entity BEGIN
            INSERT INTO search_fts(rowid, name, description, breadcrumb, tags, fields, asset_tag)
            VALUES (new.id, new.name, COALESCE(new.description, ''), new.breadcrumb,
                    '', '', COALESCE(new.asset_tag, ''));
        END""",
    "search_fts_entity_ad": """
        CREATE TRIGGER search_fts_entity_ad AFTER DELETE ON entity BEGIN
            DELETE FROM search_fts WHERE rowid = old.id;
        END""",
    "search_fts_entity_au": """
        CREATE TRIGGER search_fts_entity_au
        AFTER UPDATE OF name, description, breadcrumb, asset_tag ON entity BEGIN
            UPDATE search_fts SET name = new.name,
                description = COALESCE(new.description, ''),
                breadcrumb = new.breadcrumb,
                asset_tag = COALESCE(new.asset_tag, '')
            WHERE rowid = new.id;
        END""",
    "search_fts_entity_tag_ai": f"""
        CREATE TRIGGER search_fts_entity_tag_ai AFTER INSERT ON entity_tag BEGIN
            UPDATE search_fts SET tags = ({_TAGS_FOR.format(entity='new.entity_id')})
            WHERE rowid = new.entity_id;
        END""",
    "search_fts_entity_tag_ad": f"""
        CREATE TRIGGER search_fts_entity_tag_ad AFTER DELETE ON entity_tag BEGIN
            UPDATE search_fts SET tags = ({_TAGS_FOR.format(entity='old.entity_id')})
            WHERE rowid = old.entity_id;
        END""",
    "search_fts_tag_au": f"""
        CREATE TRIGGER search_fts_tag_au AFTER UPDATE OF name ON tag BEGIN
            UPDATE search_fts SET tags = ({_TAGS_FOR.format(entity='search_fts.rowid')})
            WHERE rowid IN (SELECT entity_id FROM entity_tag WHERE tag_id = new.id);
        END""",
    "search_fts_field_value_ai": f"""
        CREATE TRIGGER search_fts_field_value_ai AFTER INSERT ON field_value BEGIN
            UPDATE search_fts SET fields = ({_FIELDS_FOR.format(entity='new.entity_id')})
            WHERE rowid = new.entity_id;
        END""",
    "search_fts_field_value_au": f"""
        CREATE TRIGGER search_fts_field_value_au AFTER UPDATE ON field_value BEGIN
            UPDATE search_fts SET fields = ({_FIELDS_FOR.format(entity='new.entity_id')})
            WHERE rowid = new.entity_id;
        END""",
    "search_fts_field_value_ad": f"""
        CREATE TRIGGER search_fts_field_value_ad AFTER DELETE ON field_value BEGIN
            UPDATE search_fts SET fields = ({_FIELDS_FOR.format(entity='old.entity_id')})
            WHERE rowid = old.entity_id;
        END""",
    "search_fts_field_def_au": f"""
        CREATE TRIGGER search_fts_field_def_au AFTER UPDATE OF name ON field_def BEGIN
            UPDATE search_fts SET fields = ({_FIELDS_FOR.format(entity='search_fts.rowid')})
            WHERE rowid IN (SELECT entity_id FROM field_value WHERE field_def_id = new.id);
        END""",
}


def upgrade() -> None:
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(collation="NOCASE"), nullable=False, unique=True),
        sa.Column("color", sa.Text(), nullable=True),
    )
    op.create_table(
        "entity_tag",
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tag.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_entity_tag_tag_id", "entity_tag", ["tag_id"])

    op.create_table(
        "category",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(collation="NOCASE"), nullable=False, unique=True),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "field_def",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("category.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "type IN ('text','number','date','url')", name="ck_field_def_type"
        ),
        sa.UniqueConstraint("category_id", "name", name="uq_field_def_category_name"),
    )
    op.create_index("ix_field_def_category_id", "field_def", ["category_id"])

    op.create_table(
        "field_value",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_def_id",
            sa.Integer(),
            sa.ForeignKey("field_def.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_date", sa.Text(), nullable=True),
        sa.UniqueConstraint("entity_id", "field_def_id", name="uq_field_value_entity_def"),
    )
    op.create_index("ix_field_value_entity_id", "field_value", ["entity_id"])
    op.create_index("ix_field_value_field_def_id", "field_value", ["field_def_id"])

    op.create_table(
        "preset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )

    # BEFORE any entity triggers exist (batch mode recreates the entity table,
    # which would drop them). Alembic's env engine leaves foreign_keys OFF, so
    # the recreate is safe despite the FKs pointing at entity.
    with op.batch_alter_table("entity") as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_entity_category", "category", ["category_id"], ["id"], ondelete="SET NULL"
        )
    op.create_index("ix_entity_category_id", "entity", ["category_id"])

    op.execute(
        "CREATE VIRTUAL TABLE search_fts USING fts5("
        "name, description, breadcrumb, tags, fields, asset_tag, "
        "tokenize='unicode61 remove_diacritics 2', prefix='2 3')"
    )
    for ddl in TRIGGERS.values():
        op.execute(ddl)

    # Backfill live entities (metadata tables are empty -> blank tags/fields).
    op.execute(
        "INSERT INTO search_fts(rowid, name, description, breadcrumb, tags, fields, asset_tag) "
        "SELECT id, name, COALESCE(description, ''), breadcrumb, '', '', "
        "COALESCE(asset_tag, '') FROM entity"
    )


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute("DROP TABLE IF EXISTS search_fts")

    op.drop_index("ix_entity_category_id", table_name="entity")
    with op.batch_alter_table("entity") as batch_op:
        batch_op.drop_constraint("fk_entity_category", type_="foreignkey")
        batch_op.drop_column("category_id")

    op.drop_table("preset")
    op.drop_index("ix_field_value_field_def_id", table_name="field_value")
    op.drop_index("ix_field_value_entity_id", table_name="field_value")
    op.drop_table("field_value")
    op.drop_index("ix_field_def_category_id", table_name="field_def")
    op.drop_table("field_def")
    op.drop_table("category")
    op.drop_index("ix_entity_tag_tag_id", table_name="entity_tag")
    op.drop_table("entity_tag")
    op.drop_table("tag")
