"""Things to try stand apart from reading items

To try is no longer a state a feed or saved item can be put in: it holds things
(``kind="thing"``) only. Each reading item that was put in To try gets a new thing
with its title, link, description, note, and tags. The original keeps its place in
Saved, or is archived if it was only in To try, since it had already left the Inbox.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOT_THING = sa.text("kind <> 'thing'")

items = sa.table(
    "items",
    sa.column("id", sa.Integer),
    sa.column("user_id", sa.Integer),
    sa.column("url", sa.String),
    sa.column("kind", sa.String),
    sa.column("title", sa.String),
    sa.column("source", sa.String),
    sa.column("author", sa.String),
    sa.column("deck", sa.String),
    sa.column("body", sa.JSON),
    sa.column("copy", sa.String),
    sa.column("note", sa.String),
    sa.column("video_id", sa.String),
    sa.column("published_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("saved_at", sa.DateTime(timezone=True)),
    sa.column("try_at", sa.DateTime(timezone=True)),
    sa.column("archived_at", sa.DateTime(timezone=True)),
)
item_tags = sa.table(
    "item_tags", sa.column("item_id", sa.Integer), sa.column("tag_id", sa.Integer)
)


def upgrade() -> None:
    # A thing may share its link with a reading item, so uniqueness covers reading
    # items only.
    with op.batch_alter_table("items") as batch:
        batch.drop_constraint("uq_items_user_id", type_="unique")

    conn = op.get_bind()
    now = datetime.now(UTC)
    promoted = conn.execute(
        sa.select(items).where(items.c.try_at.is_not(None), items.c.kind != "thing")
    ).all()
    for row in promoted:
        thing_id = conn.execute(
            sa.insert(items)
            .values(
                user_id=row.user_id,
                url=row.url,
                kind="thing",
                title=row.title,
                source=row.source,
                author="",
                deck=row.deck,
                body=[],
                copy="link",
                note=row.note,
                video_id=None,
                published_at=row.try_at,
                created_at=row.try_at,
                saved_at=None,
                try_at=row.try_at,
                archived_at=row.archived_at,
            )
            .returning(items.c.id)
        ).scalar_one()
        tag_ids = conn.scalars(
            sa.select(item_tags.c.tag_id).where(item_tags.c.item_id == row.id)
        ).all()
        if tag_ids:
            conn.execute(
                sa.insert(item_tags),
                [{"item_id": thing_id, "tag_id": t} for t in tag_ids],
            )
        if row.saved_at is None and row.archived_at is None:
            conn.execute(
                sa.update(items).where(items.c.id == row.id).values(archived_at=now)
            )

    with op.batch_alter_table("items") as batch:
        batch.drop_column("try_at")
    # Created last: SQLite batch operations rebuild the table and may not keep a
    # partial index's WHERE clause.
    op.create_index(
        "uq_items_user_id_url",
        "items",
        ["user_id", "url"],
        unique=True,
        sqlite_where=NOT_THING,
        postgresql_where=NOT_THING,
    )


def downgrade() -> None:
    op.drop_index("uq_items_user_id_url", table_name="items")
    # The old unique constraint covers things too: drop linked things whose link is
    # also a reading item or an earlier thing.
    op.execute(
        "DELETE FROM items WHERE kind = 'thing' AND url IS NOT NULL AND ("
        "EXISTS (SELECT 1 FROM items AS r WHERE r.user_id = items.user_id "
        "AND r.url = items.url AND (r.kind <> 'thing' OR r.id < items.id)))"
    )
    with op.batch_alter_table("items") as batch:
        batch.add_column(sa.Column("try_at", sa.DateTime(timezone=True)))
        batch.create_unique_constraint("uq_items_user_id", ["user_id", "url"])
    op.execute("UPDATE items SET try_at = created_at WHERE kind = 'thing'")
