"""Library business logic: saving links, things to try, feeds, triage.

The service receives its collaborators (a repository, a fetcher, and a clock) from
the caller, so tests use a real SQLite repository with a fake fetcher and clock.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

import structlog

from shelfmark.clients.fetcher import BlockedURLError, Fetcher, FetchError
from shelfmark.models import Feed, Item
from shelfmark.repositories.library import LibraryRepository
from shelfmark.services.content import Article, extract_article, plain_text
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
VIEWS = frozenset({"inbox", "saved", "try", "archive", "feed", "tag"})
MAX_NOTE_CHARS = 2000
MAX_TAGS = 20
MAX_TAG_CHARS = 50
MAX_DECK_CHARS = 300


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


def clean_note(raw: str) -> str:
    lines = [" ".join(line.split()) for line in raw.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()[:MAX_NOTE_CHARS]


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
        note: str | None = None,
    ) -> Item:
        item = await self.item(user_id, item_id)
        now = self.clock()
        # Saving is a deliberate choice; it pulls an item out of Archive. Unsaving
        # leaves the archive state alone.
        if saved is not None:
            if saved and item.kind == "thing":
                raise LibraryError(
                    "Things to try stay in To try. Archive one once you have tried it."
                )
            item.saved_at = (item.saved_at or now) if saved else None
            if saved:
                item.archived_at = None
        if note is not None:
            item.note = clean_note(note)
        if archived is not None:
            item.archived_at = (item.archived_at or now) if archived else None
        if tags is not None:
            await self.repo.set_tags(item, clean_tags(tags))
        await self.repo.commit()
        return await self.repo.refresh_item(item)

    # Saving links

    async def save_link(
        self, user_id: int, raw_url: str, title: str = "", *, note: str = ""
    ) -> SaveResult:
        """Save an article or video link to Saved, extracting a reading copy."""
        title = plain_text(title, 400)
        note = clean_note(note)
        url = _parse(raw_url)
        key = canonical_item_url(url)
        existing = await self.repo.item_by_url(user_id, key)
        if existing is not None:
            existing.saved_at = existing.saved_at or self.clock()
            existing.archived_at = None
            if title:
                existing.title = title
            if note:
                existing.note = note
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
        item.saved_at = self.clock()
        return await self._create(user_id, item, note, [])

    async def add_thing(
        self,
        user_id: int,
        name: str,
        raw_url: str = "",
        *,
        description: str = "",
        note: str = "",
        tags: list[str] | None = None,
    ) -> SaveResult:
        """Add a tool, repo, skill, or idea to To try: a name and/or a link.

        The link is kept as a link, never read as an article. Without a name, the
        page's title and description fill in the name and description.
        """
        name = plain_text(name, 400)
        description = plain_text(description, MAX_DECK_CHARS)
        note = clean_note(note)
        url = canonical_item_url(_parse(raw_url)) if raw_url.strip() else None
        if not name and not url:
            raise LibraryError("Give it a name or a link.")
        if url:
            existing = await self.repo.item_by_url(user_id, url, thing=True)
            if existing is not None:
                existing.archived_at = None
                existing.title = name or existing.title
                existing.deck = description or existing.deck
                existing.note = note or existing.note
                if tags:
                    names = [t.name for t in existing.tags] + tags
                    await self.repo.set_tags(existing, clean_tags(names))
                await self.repo.commit()
                return SaveResult(await self.repo.refresh_item(existing), created=False)
        if url and not name:
            page = await self._read_page(url)
            name = github_repo_name(url) or (page.title if page else "")
            name = name or site_name(url)
            description = description or (page.deck if page else "")
        thing = Item(
            url=url,
            kind="thing",
            title=name,
            source=site_name(url) if url else "",
            deck=description[:MAX_DECK_CHARS],
            copy="link" if url else "none",
            body=[],
        )
        return await self._create(user_id, thing, note, clean_tags(tags or []))

    async def _create(
        self, user_id: int, item: Item, note: str, tags: list[str]
    ) -> SaveResult:
        now = self.clock()
        item.user_id = user_id
        item.note = note
        item.published_at = item.created_at = now
        await self.repo.add_item(item)
        if tags:
            await self.repo.set_tags(item, tags)
        await self.repo.commit()
        return SaveResult(await self.repo.refresh_item(item), created=True)

    async def _read_page(self, url: str) -> Article | None:
        """Extract the article at ``url``; ``None`` when it cannot be read.

        Raises ``LibraryError`` when the URL leads somewhere other than a public
        website.
        """
        try:
            page = await self.fetcher.fetch(url)
        except BlockedURLError as error:
            raise LibraryError(str(error)) from error
        except FetchError as error:
            # The link is still worth keeping when the publisher refuses extraction.
            log.info("article_fetch_failed", url=url, reason=str(error))
            return None
        if "html" not in page.content_type and "<html" not in page.text[:2000].lower():
            return None
        return extract_article(page.text)

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
        article = await self._read_page(url)
        if article is None:
            return item
        if article.title and not title:
            item.title = github_repo_name(url) or article.title
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


def github_repo_name(url: str) -> str | None:
    """``owner/repo`` for a GitHub repository URL; its page title is too long."""
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if parts.hostname in ("github.com", "www.github.com") and len(segments) == 2:
        return "/".join(segments)
    return None


def _parse(raw_url: str) -> str:
    try:
        return parse_web_url(raw_url)
    except WebURLError as error:
        raise LibraryError(str(error)) from error
