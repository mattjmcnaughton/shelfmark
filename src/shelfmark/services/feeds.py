"""RSS and Atom parsing into plain data, and feed discovery on web pages."""

import calendar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin

import feedparser
import lxml.html
from lxml import etree

from shelfmark.services.content import Block, html_to_blocks, plain_text, word_count
from shelfmark.services.urls import WebURLError, parse_web_url

MAX_ENTRIES = 60
# A feed entry without full content and with a summary shorter than this is a
# teaser; the article itself is fetched from its link.
FULL_TEXT_WORDS = 200
FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml"})


class FeedFormatError(ValueError):
    def __init__(self) -> None:
        super().__init__("That URL did not return a valid RSS or Atom feed.")


@dataclass(frozen=True)
class FeedEntry:
    url: str
    title: str
    author: str
    published_at: datetime | None
    blocks: list[Block] = field(default_factory=list)
    # Only a summary: the full article is on the linked page.
    partial: bool = False


@dataclass(frozen=True)
class ParsedFeed:
    title: str
    entries: list[FeedEntry]


def parse_feed(text: str, base_url: str) -> ParsedFeed:
    # feedparser never fetches when given a string, so this is offline parsing.
    parsed = feedparser.parse(text, response_headers={"content-location": base_url})
    version = parsed.get("version") or ""
    if not version or (parsed.get("bozo") and not parsed.entries and not version):
        raise FeedFormatError
    entries: list[FeedEntry] = []
    for entry in parsed.entries[:MAX_ENTRIES]:
        link = entry.get("link") or ""
        try:
            url = parse_web_url(link)
        except WebURLError:
            continue
        content = entry.content[0].get("value", "") if entry.get("content") else ""
        blocks = html_to_blocks(content or entry.get("summary", ""))
        when = entry.get("published_parsed") or entry.get("updated_parsed")
        entries.append(
            FeedEntry(
                url=url,
                title=plain_text(entry.get("title", ""), 400),
                author=plain_text(entry.get("author", ""), 200),
                published_at=(
                    datetime.fromtimestamp(calendar.timegm(when), UTC) if when else None
                ),
                blocks=blocks,
                partial=not content and word_count(blocks) < FULL_TEXT_WORDS,
            )
        )
    return ParsedFeed(
        title=plain_text(parsed.feed.get("title", ""), 200), entries=entries
    )


def discover_feed_url(html: str, base_url: str) -> str | None:
    """The first RSS or Atom feed a page advertises in ``<link rel=alternate>``."""
    try:
        root = lxml.html.document_fromstring(html)
    except (etree.ParserError, ValueError):
        return None
    for link in root.iter("link"):
        rel = str(link.get("rel") or "").lower().split()
        kind = str(link.get("type") or "").lower().split(";")[0].strip()
        href = str(link.get("href") or "").strip()
        if "alternate" in rel and kind in FEED_TYPES and href:
            try:
                return parse_web_url(urljoin(base_url, href))
            except WebURLError:
                continue
    return None
