"""Library business logic: saving links, following feeds, triage.

The service receives its collaborators (a repository, a fetcher, and a clock) from
the caller, so tests use a real SQLite repository with a fake fetcher and clock.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

import structlog

from shelfmark.clients.fetcher import BlockedURLError, Fetcher, FetchError
from shelfmark.models import Feed, Item
from shelfmark.repositories.library import LibraryRepository
from shelfmark.services.content import extract_article, plain_text
from shelfmark.services.feeds import FeedFormatError, parse_feed
from shelfmark.services.urls import (
    WebURLError,
    canonical_item_url,
    parse_web_url,
    site_name,
    youtube_video_id,
)

log = structlog.get_logger()

Clock = Callable[[], datetime]
VIEWS = frozenset({"inbox", "saved", "archive", "feed", "tag"})
MAX_TAGS = 20
MAX_TAG_CHARS = 50


def utc_now() -> datetime:
    return datetime.now(UTC)


class LibraryError(Exception):
    """A request the user can fix; ``status`` maps to HTTP."""

    status = 400


class NotFoundError(LibraryError):
    status = 404


class ConflictError(LibraryError):
    status = 409


@dataclass(frozen=True)
class SaveResult:
    item: Item
    created: bool


def clean_tags(raw: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in raw:
        name = " ".join(str(value).split()).lower()[:MAX_TAG_CHARS]
        if name:
            seen.setdefault(name, None)
    return list(seen)[:MAX_TAGS]


class LibraryService:
    def __init__(
        self, repo: LibraryRepository, fetcher: Fetcher, clock: Clock = utc_now
    ) -> None:
        self.repo = repo
        self.fetcher = fetcher
        self.clock = clock

    # Reading

    async def items(
        self, user_id: int, view: str, feed_id: int | None, tag: str | None
    ) -> list[Item]:
        if view not in VIEWS:
            raise LibraryError("Unknown view.")
        if view == "feed" and (
            feed_id is None or not await self.repo.feed(user_id, feed_id)
        ):
            raise NotFoundError("Feed not found.")
        if view == "tag" and not tag:
            raise LibraryError("Choose a tag.")
        return list(await self.repo.list_items(user_id, view, feed_id=feed_id, tag=tag))

    async def item(self, user_id: int, item_id: int) -> Item:
        item = await self.repo.item(user_id, item_id)
        if item is None:
            raise NotFoundError("Item not found.")
        return item

    # Triage

    async def update(
        self,
        user_id: int,
        item_id: int,
        *,
        saved: bool | None = None,
        archived: bool | None = None,
        tags: list[str] | None = None,
    ) -> Item:
        item = await self.item(user_id, item_id)
        now = self.clock()
        if saved is not None:
            item.saved_at = (item.saved_at or now) if saved else None
            if saved:
                # Saving is a deliberate "read this"; it pulls an item out of Archive.
                item.archived_at = None
        if archived is not None:
            item.archived_at = (item.archived_at or now) if archived else None
        if tags is not None:
            await self.repo.set_tags(item, clean_tags(tags))
        await self.repo.commit()
        return await self.repo.refresh_item(item)

    # Saving links

    async def save_link(
        self, user_id: int, raw_url: str, title: str = ""
    ) -> SaveResult:
        url = _parse(raw_url)
        title = plain_text(title, 400)
        key = canonical_item_url(url)
        now = self.clock()
        existing = await self.repo.item_by_url(user_id, key)
        if existing is not None:
            existing.saved_at = existing.saved_at or now
            existing.archived_at = None
            if title:
                existing.title = title
            await self.repo.commit()
            return SaveResult(await self.repo.refresh_item(existing), created=False)

        video = youtube_video_id(url)
        if video:
            item = Item(
                url=key,
                kind="video",
                title=title or await self._youtube_title(key) or "YouTube video",
                source="YouTube",
                copy="link",
                video_id=video,
                body=[],
            )
        else:
            item = await self._article(url, title)
        item.user_id = user_id
        item.published_at = item.created_at = item.saved_at = now
        await self.repo.add_item(item)
        await self.repo.commit()
        return SaveResult(await self.repo.refresh_item(item), created=True)

    async def _article(self, url: str, title: str) -> Item:
        item = Item(
            url=url,
            kind="article",
            title=title or site_name(url),
            source=site_name(url),
            author="",
            deck="",
            copy="link",
            body=[],
        )
        try:
            page = await self.fetcher.fetch(url)
        except BlockedURLError as error:
            raise LibraryError(str(error)) from error
        except FetchError as error:
            # The link is still worth saving when the publisher refuses extraction.
            log.info("article_fetch_failed", url=url, reason=str(error))
            return item
        if "html" not in page.content_type and "<html" not in page.text[:2000].lower():
            return item
        article = extract_article(page.text)
        if article.title and not title:
            item.title = article.title
        if article.blocks:
            item.body = article.blocks
            item.author = article.author
            item.deck = article.deck
            item.copy = "extracted"
        return item

    async def _youtube_title(self, url: str) -> str:
        oembed = "https://www.youtube.com/oembed?" + urlencode(
            {"url": url, "format": "json"}
        )
        try:
            data = json.loads((await self.fetcher.fetch(oembed)).text)
        except (FetchError, ValueError):
            return ""
        return (
            plain_text(str(data.get("title", "")), 400)
            if isinstance(data, dict)
            else ""
        )

    # Feeds

    async def follow(self, user_id: int, raw_url: str, title: str = "") -> Feed:
        url = _parse(raw_url)
        if await self.repo.feed_by_url(user_id, url):
            raise ConflictError("You already follow this feed.")
        parsed = await self._fetch_feed(url)
        now = self.clock()
        feed = await self.repo.add_feed(
            Feed(
                user_id=user_id,
                url=url,
                title=plain_text(title, 200) or parsed.title or site_name(url),
                checked_at=now,
                error=None,
                created_at=now,
            )
        )
        await self._import(feed, parsed.entries)
        await self.repo.commit()
        return feed

    async def refresh_user(self, user_id: int) -> list[Feed]:
        feeds = list(await self.repo.feeds(user_id))
        for feed in feeds:
            await self.refresh_feed(feed)
        return feeds

    async def refresh_feed(self, feed: Feed) -> None:
        try:
            parsed = await self._fetch_feed(feed.url)
        except LibraryError as error:
            feed.error = str(error)[:300]
        else:
            await self._import(feed, parsed.entries)
            feed.error = None
        feed.checked_at = self.clock()
        await self.repo.commit()

    async def _fetch_feed(self, url: str):
        try:
            page = await self.fetcher.fetch(url)
            return parse_feed(page.text, page.url)
        except (FetchError, FeedFormatError) as error:
            raise LibraryError(str(error)) from error

    async def _import(self, feed: Feed, entries) -> None:
        now = self.clock()
        for entry in entries:
            key = canonical_item_url(entry.url)
            item = await self.repo.item_by_url(feed.user_id, key)
            if item is None:
                video = youtube_video_id(entry.url)
                item = await self.repo.add_item(
                    Item(
                        user_id=feed.user_id,
                        url=key,
                        kind="video" if video else "article",
                        title=entry.title or site_name(entry.url),
                        source=feed.title,
                        author=entry.author,
                        deck="",
                        body=[] if video else entry.blocks,
                        copy="feed" if entry.blocks and not video else "link",
                        video_id=video,
                        published_at=entry.published_at or now,
                        created_at=now,
                    )
                )
            await self.repo.link_entry(feed.id, item.id)


def _parse(raw_url: str) -> str:
    try:
        return parse_web_url(raw_url)
    except WebURLError as error:
        raise LibraryError(str(error)) from error
