"""SQLAlchemy models.

Types and constraints stay portable across SQLite and Postgres: no dialect-specific
column types, JSON through ``sqlalchemy.JSON``, timezone-aware timestamps stored as
UTC, and named constraints so Alembic can diff either backend.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC timestamps on every backend.

    Postgres keeps the offset natively; SQLite drops it, so values are normalized to
    UTC on the way in and tagged as UTC on the way out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


Timestamp = UTCDateTime


class User(Base):
    """A person, identified by an external auth provider's stable subject."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(Timestamp)


feed_entries = Table(
    "feed_entries",
    Base.metadata,
    Column("feed_id", ForeignKey("feeds.id", ondelete="CASCADE"), primary_key=True),
    Column("item_id", ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
)

item_tags = Table(
    "item_tags",
    Base.metadata,
    Column("item_id", ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Feed(Base):
    __tablename__ = "feeds"
    __table_args__ = (UniqueConstraint("user_id", "url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(200))
    checked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(Timestamp)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))


# Reading items (articles, videos) are one per URL. Things to try live apart from
# them, so a repo can be both a saved article and a thing to try.
NOT_THING = text("kind <> 'thing'")


class Item(Base):
    """Something to read or watch (a feed entry or a saved link), or a thing to try.

    Things to try (``kind="thing"``) are link aggregation, not reading: a name, an
    optional link, a short description (``deck``), a note, and tags. They are never
    fetched as articles and always sit in To try until archived (tried).
    """

    __tablename__ = "items"
    __table_args__ = (
        Index(
            "uq_items_user_id_url",
            "user_id",
            "url",
            unique=True,
            sqlite_where=NOT_THING,
            postgresql_where=NOT_THING,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Null for a thing to try that has no link.
    url: Mapped[str | None] = mapped_column(String(2048))
    kind: Mapped[str] = mapped_column(String(16))  # article | video | thing
    title: Mapped[str] = mapped_column(String(400))
    source: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(200), default="")
    deck: Mapped[str] = mapped_column(String(300), default="")
    # Plain-text blocks: [{"text": str, "heading": bool}]. Never HTML.
    body: Mapped[list[dict]] = mapped_column(JSON, default=list)
    copy: Mapped[str] = mapped_column(String(16))  # feed | extracted | link | none
    note: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    video_id: Mapped[str | None] = mapped_column(String(11))
    published_at: Mapped[datetime] = mapped_column(Timestamp, index=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp)
    saved_at: Mapped[datetime | None] = mapped_column(Timestamp)
    archived_at: Mapped[datetime | None] = mapped_column(Timestamp)

    tags: Mapped[list[Tag]] = relationship(
        secondary=item_tags, lazy="selectin", order_by=Tag.name
    )
    feeds: Mapped[list[Feed]] = relationship(secondary=feed_entries, lazy="selectin")


__all__ = [
    "Base",
    "Feed",
    "Item",
    "Tag",
    "User",
    "feed_entries",
    "item_tags",
]
