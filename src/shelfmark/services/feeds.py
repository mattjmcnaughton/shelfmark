"""RSS and Atom parsing into plain data."""

import calendar
from dataclasses import dataclass, field
from datetime import UTC, datetime

import feedparser

from shelfmark.services.content import Block, html_to_blocks, plain_text
from shelfmark.services.urls import WebURLError, parse_web_url

MAX_ENTRIES = 60


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
        html = ""
        if entry.get("content"):
            html = entry.content[0].get("value", "")
        html = html or entry.get("summary", "")
        when = entry.get("published_parsed") or entry.get("updated_parsed")
        entries.append(
            FeedEntry(
                url=url,
                title=plain_text(entry.get("title", ""), 400),
                author=plain_text(entry.get("author", ""), 200),
                published_at=(
                    datetime.fromtimestamp(calendar.timegm(when), UTC) if when else None
                ),
                blocks=html_to_blocks(html),
            )
        )
    return ParsedFeed(
        title=plain_text(parsed.feed.get("title", ""), 200), entries=entries
    )
