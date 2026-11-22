"""Data access for users, feeds, items, and tags.

Queries use only portable SQLAlchemy Core/ORM constructs (no SQLite JSON functions,
no ``INSERT OR IGNORE``), so the same code runs on Postgres.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, delete, exists, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from shelfmark.models import Feed, Item, Tag, User, feed_entries, item_tags

MAX_LIST = 500


class LibraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    # Users

    async def get_or_create_user(
        self, provider: str, subject: str, name: str, email: str | None, now: datetime
    ) -> User:
        user = await self.session.scalar(
            select(User).where(User.provider == provider, User.subject == subject)
        )
        if user is None:
            user = User(
                provider=provider,
                subject=subject,
                display_name=name,
                email=email,
                created_at=now,
            )
            self.session.add(user)
        else:
            user.display_name, user.email = name, email
        await self.session.flush()
        return user

    async def all_user_ids(self) -> Sequence[int]:
        return (await self.session.scalars(select(User.id))).all()

    # Feeds

    async def feeds(self, user_id: int) -> Sequence[Feed]:
        return (
            await self.session.scalars(
                select(Feed)
                .where(Feed.user_id == user_id)
                .order_by(func.lower(Feed.title), Feed.id)
            )
        ).all()

    async def feed(self, user_id: int, feed_id: int) -> Feed | None:
        return await self.session.scalar(
            select(Feed).where(Feed.user_id == user_id, Feed.id == feed_id)
        )

    async def feed_by_url(self, user_id: int, url: str) -> Feed | None:
        return await self.session.scalar(
            select(Feed).where(Feed.user_id == user_id, Feed.url == url)
        )

    async def add_feed(self, feed: Feed) -> Feed:
        self.session.add(feed)
        await self.session.flush()
        return feed

    async def link_entry(self, feed_id: int, item_id: int) -> None:
        linked = await self.session.scalar(
            select(
                exists().where(
                    feed_entries.c.feed_id == feed_id, feed_entries.c.item_id == item_id
                )
            )
        )
        if not linked:
            await self.session.execute(
                insert(feed_entries).values(feed_id=feed_id, item_id=item_id)
            )

    # Items

    async def item(self, user_id: int, item_id: int) -> Item | None:
        return await self.session.scalar(
            select(Item).where(Item.user_id == user_id, Item.id == item_id)
        )

    async def item_by_url(self, user_id: int, url: str) -> Item | None:
        return await self.session.scalar(
            select(Item).where(Item.user_id == user_id, Item.url == url)
        )

    async def add_item(self, item: Item) -> Item:
        self.session.add(item)
        await self.session.flush()
        return item

    async def refresh_item(self, item: Item) -> Item:
        await self.session.refresh(item, ["tags", "feeds"])
        return item

    async def list_items(
        self,
        user_id: int,
        view: str,
        *,
        feed_id: int | None = None,
        tag: str | None = None,
    ) -> Sequence[Item]:
        query = select(Item).where(Item.user_id == user_id)
        not_archived = Item.archived_at.is_(None)
        if view == "inbox":
            query = query.where(
                not_archived, Item.saved_at.is_(None), Item.try_at.is_(None)
            )
        elif view == "saved":
            query = query.where(not_archived, Item.saved_at.is_not(None))
        elif view == "try":
            query = query.where(not_archived, Item.try_at.is_not(None))
        elif view == "archive":
            query = query.where(Item.archived_at.is_not(None))
        elif view == "feed":
            query = query.where(
                not_archived,
                exists().where(
                    feed_entries.c.item_id == Item.id, feed_entries.c.feed_id == feed_id
                ),
            )
        elif view == "tag":
            query = query.where(
                exists()
                .where(item_tags.c.item_id == Item.id)
                .where(
                    item_tags.c.tag_id.in_(
                        select(Tag.id).where(Tag.user_id == user_id, Tag.name == tag)
                    )
                )
            )
        else:
            raise ValueError(view)
        query = query.order_by(Item.published_at.desc(), Item.id.desc()).limit(MAX_LIST)
        return (await self.session.scalars(query)).all()

    async def counts(self, user_id: int) -> dict[str, int]:
        mine = Item.user_id == user_id
        live = Item.archived_at.is_(None)

        async def count(*where) -> int:
            return (
                await self.session.scalar(select(func.count(Item.id)).where(*where))
            ) or 0

        return {
            "inbox": await count(
                mine, live, Item.saved_at.is_(None), Item.try_at.is_(None)
            ),
            "saved": await count(mine, live, Item.saved_at.is_not(None)),
            "try": await count(mine, live, Item.try_at.is_not(None)),
            "archive": await count(mine, Item.archived_at.is_not(None)),
        }

    # Tags

    async def tag_names(self, user_id: int) -> list[str]:
        """Tags in use on at least one item."""
        used = exists().where(item_tags.c.tag_id == Tag.id)
        return list(
            (
                await self.session.scalars(
                    select(Tag.name)
                    .where(Tag.user_id == user_id, used)
                    .order_by(Tag.name)
                )
            ).all()
        )

    async def set_tags(self, item: Item, names: list[str]) -> None:
        tags: list[Tag] = []
        for name in names:
            tag = await self.session.scalar(
                select(Tag).where(and_(Tag.user_id == item.user_id, Tag.name == name))
            )
            if tag is None:
                tag = Tag(user_id=item.user_id, name=name)
                self.session.add(tag)
                await self.session.flush()
            tags.append(tag)
        await self.session.execute(
            delete(item_tags).where(item_tags.c.item_id == item.id)
        )
        if tags:
            await self.session.execute(
                insert(item_tags), [{"item_id": item.id, "tag_id": t.id} for t in tags]
            )
        await self.session.flush()
        await self.refresh_item(item)
