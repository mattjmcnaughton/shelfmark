"""API request and response models, kept separate from the database models."""

from datetime import datetime

from pydantic import BaseModel, Field

from shelfmark.models import Feed, Item


class UserOut(BaseModel):
    name: str
    can_sign_out: bool


class FeedOut(BaseModel):
    id: int
    url: str
    title: str
    checked_at: datetime | None
    error: str | None

    @classmethod
    def of(cls, feed: Feed) -> "FeedOut":
        return cls(
            id=feed.id,
            url=feed.url,
            title=feed.title,
            checked_at=feed.checked_at,
            error=feed.error,
        )


class Counts(BaseModel):
    inbox: int
    saved: int
    archive: int


class LibraryOut(BaseModel):
    user: UserOut
    feeds: list[FeedOut]
    tags: list[str]
    counts: Counts


class Block(BaseModel):
    text: str
    heading: bool


class ItemSummary(BaseModel):
    id: int
    url: str
    kind: str
    title: str
    source: str
    author: str
    deck: str
    video_id: str | None
    published_at: datetime
    saved: bool
    archived: bool
    tags: list[str]
    feed_ids: list[int]
    copy_: str = Field(serialization_alias="copy")

    @classmethod
    def fields_of(cls, item: Item) -> dict:
        return {
            "id": item.id,
            "url": item.url,
            "kind": item.kind,
            "title": item.title,
            "source": item.source,
            "author": item.author,
            "deck": item.deck,
            "video_id": item.video_id,
            "published_at": item.published_at,
            "saved": item.saved_at is not None,
            "archived": item.archived_at is not None,
            "tags": [t.name for t in item.tags],
            "feed_ids": sorted(f.id for f in item.feeds),
            "copy_": item.copy,
        }

    @classmethod
    def of(cls, item: Item) -> "ItemSummary":
        return cls(**cls.fields_of(item))


class ItemDetail(ItemSummary):
    body: list[Block]

    @classmethod
    def of(cls, item: Item) -> "ItemDetail":
        return cls(
            **ItemSummary.fields_of(item),
            body=[
                Block(text=str(b["text"]), heading=bool(b["heading"]))
                for b in item.body
            ],
        )


class ItemList(BaseModel):
    items: list[ItemSummary]


class FeedList(BaseModel):
    feeds: list[FeedOut]


class LinkIn(BaseModel):
    url: str = Field(max_length=2048)
    title: str = Field("", max_length=400)


class ItemPatch(BaseModel):
    saved: bool | None = None
    archived: bool | None = None
    tags: list[str] | None = Field(None, max_length=50)
