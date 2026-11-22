"""LibraryService against a real SQLite database with a fake fetcher and clock."""

import pytest

from shelfmark.clients.fetcher import BlockedURLError, FetchError
from shelfmark.repositories.library import LibraryRepository
from shelfmark.services.library import ConflictError, LibraryError, LibraryService
from tests.fakes import ARTICLE, FakeClock, FakeFetcher, rss

pytestmark = pytest.mark.anyio
FEED = "https://blog.example.com/feed.xml"


async def service(database, fetcher, clock):
    async with database.session() as session:
        repo = LibraryRepository(session)
        user = await repo.get_or_create_user("test", "u1", "Reader", None, clock())
        await repo.commit()
    session = database._sessions()
    return LibraryService(LibraryRepository(session), fetcher, clock), user.id, session


async def titles(svc, user_id, view, **kw):
    return [
        i.title
        for i in await svc.items(user_id, view, kw.get("feed_id"), kw.get("tag"))
    ]


async def test_feed_entries_land_in_inbox_and_refresh_adds_only_new(database):
    clock = FakeClock()
    fetcher = FakeFetcher(
        {
            FEED: rss(
                "Example Blog",
                (
                    "Older",
                    "https://blog.example.com/1",
                    "Thu, 19 Nov 2026 09:00:00 GMT",
                    "<p>one</p>",
                ),
                (
                    "Newer",
                    "https://blog.example.com/2",
                    "Fri, 20 Nov 2026 09:00:00 GMT",
                    "<p>two</p>",
                ),
            )
        }
    )
    svc, uid, session = await service(database, fetcher, clock)
    feed = await svc.follow(uid, FEED)
    assert feed.title == "Example Blog"
    assert await titles(svc, uid, "inbox") == ["Newer", "Older"]
    assert await titles(svc, uid, "feed", feed_id=feed.id) == ["Newer", "Older"]

    with pytest.raises(ConflictError):
        await svc.follow(uid, FEED)

    # Archive one, then refresh with a new entry plus the old ones: the archived
    # entry must stay archived and must not be duplicated.
    older = (await svc.items(uid, "inbox", None, None))[1]
    await svc.update(uid, older.id, archived=True)
    fetcher.pages[FEED] = rss(
        "Example Blog",
        (
            "Newest",
            "https://blog.example.com/3",
            "Sat, 21 Nov 2026 09:00:00 GMT",
            "<p>3</p>",
        ),
        (
            "Newer",
            "https://blog.example.com/2",
            "Fri, 20 Nov 2026 09:00:00 GMT",
            "<p>two</p>",
        ),
        (
            "Older",
            "https://blog.example.com/1",
            "Thu, 19 Nov 2026 09:00:00 GMT",
            "<p>one</p>",
        ),
    )
    clock.advance(minutes=20)
    await svc.refresh_user(uid)
    assert await titles(svc, uid, "inbox") == ["Newest", "Newer"]
    assert await titles(svc, uid, "archive") == ["Older"]
    assert feed.checked_at == clock.now and feed.error is None

    # A failing refresh records the error and keeps existing items.
    fetcher.pages[FEED] = FetchError("The site returned HTTP 500.")
    await svc.refresh_user(uid)
    assert feed.error == "The site returned HTTP 500."
    assert await titles(svc, uid, "inbox") == ["Newest", "Newer"]
    await session.close()


async def test_saved_queue_is_separate_from_inbox_and_archive_restores(database):
    fetcher = FakeFetcher(
        {
            FEED: rss(
                "B",
                (
                    "Post",
                    "https://blog.example.com/p",
                    "Fri, 20 Nov 2026 09:00:00 GMT",
                    "<p>x</p>",
                ),
            )
        }
    )
    svc, uid, session = await service(database, fetcher, FakeClock())
    await svc.follow(uid, FEED)
    post = (await svc.items(uid, "inbox", None, None))[0]

    await svc.update(uid, post.id, saved=True)
    assert await titles(svc, uid, "inbox") == []
    assert await titles(svc, uid, "saved") == ["Post"]

    await svc.update(uid, post.id, archived=True)
    assert await titles(svc, uid, "saved") == []
    assert await titles(svc, uid, "archive") == ["Post"]

    # Restoring a saved item puts it back in Saved, not the Inbox.
    await svc.update(uid, post.id, archived=False)
    assert await titles(svc, uid, "saved") == ["Post"]
    assert await titles(svc, uid, "inbox") == []

    # Unsaving and saving from Archive: saving pulls it out of Archive.
    await svc.update(uid, post.id, saved=False, archived=True)
    await svc.update(uid, post.id, saved=True)
    assert await titles(svc, uid, "saved") == ["Post"]
    await session.close()


async def test_save_article_extracts_plain_text_and_falls_back_to_link(database):
    url = "https://news.example.org/slow-reading"
    fetcher = FakeFetcher({url: ARTICLE})
    svc, uid, session = await service(database, fetcher, FakeClock())

    result = await svc.save_link(uid, url + "#comments")
    item = result.item
    assert result.created and item.copy == "extracted" and item.url == url
    assert item.title == "Slow Reading - Example" and item.author == "Ada Lovelace"
    text = " ".join(str(b["text"]) for b in item.body)
    assert "attention compounds" in text
    assert "steal" not in text and "<" not in text
    assert {"text": "Why", "heading": True} in item.body

    # Saving the same URL again does not duplicate it.
    again = await svc.save_link(uid, url)
    assert not again.created and again.item.id == item.id

    # The publisher refuses: the link is still saved, with the link-only fallback.
    paywalled = await svc.save_link(uid, "https://paywall.example.net/story")
    assert paywalled.item.copy == "link" and paywalled.item.body == []
    assert paywalled.item.title == "paywall.example.net"
    assert await titles(svc, uid, "saved") == [
        "paywall.example.net",
        "Slow Reading - Example",
    ]

    # A blocked destination (e.g. a redirect into a private network) is refused.
    fetcher.pages["https://evil.example.com/"] = BlockedURLError()
    with pytest.raises(LibraryError, match="public websites"):
        await svc.save_link(uid, "https://evil.example.com/")
    with pytest.raises(LibraryError):
        await svc.save_link(uid, "file:///etc/passwd")
    await session.close()


async def test_youtube_links_become_one_video_item(database):
    oembed = (
        "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DdQw4w9WgXcQ"
        "&format=json"
    )
    fetcher = FakeFetcher({oembed: '{"title": "A <b>talk</b>"}'})
    svc, uid, session = await service(database, fetcher, FakeClock())
    first = await svc.save_link(uid, "https://youtu.be/dQw4w9WgXcQ?t=42")
    assert first.item.kind == "video" and first.item.video_id == "dQw4w9WgXcQ"
    assert first.item.title == "A talk"
    second = await svc.save_link(uid, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert second.item.id == first.item.id and not second.created
    await session.close()


async def test_tags_are_normalized_and_filter_across_views(database):
    svc, uid, session = await service(
        database, FakeFetcher({"https://a.example.com/": ARTICLE}), FakeClock()
    )
    item = (await svc.save_link(uid, "https://a.example.com/")).item
    await svc.update(uid, item.id, tags=["  Design ", "design", "", "Later reading"])
    assert [t.name for t in item.tags] == ["design", "later reading"]
    await svc.update(uid, item.id, archived=True)
    # Tag views include archived items.
    assert await titles(svc, uid, "tag", tag="design") == [item.title]
    assert await svc.repo.tag_names(uid) == ["design", "later reading"]
    await svc.update(uid, item.id, tags=[])
    assert await svc.repo.tag_names(uid) == []
    await session.close()


async def test_users_cannot_see_each_others_items(database):
    clock = FakeClock()
    svc, uid, session = await service(database, FakeFetcher(), clock)
    item = (await svc.save_link(uid, "https://a.example.com/x")).item
    other = await svc.repo.get_or_create_user("test", "u2", "Other", None, clock())
    await svc.repo.commit()
    assert await svc.items(other.id, "saved", None, None) == []
    with pytest.raises(LibraryError):
        await svc.item(other.id, item.id)
    await session.close()


async def test_to_try_queue_holds_named_things_and_promoted_feed_items(database):
    fetcher = FakeFetcher(
        {
            FEED: rss(
                "B",
                (
                    "Tool post",
                    "https://blog.example.com/t",
                    "Fri, 20 Nov 2026 09:00:00 GMT",
                    "<p>x</p>",
                ),
                (
                    "Other",
                    "https://blog.example.com/o",
                    "Thu, 19 Nov 2026 09:00:00 GMT",
                    "<p>y</p>",
                ),
            ),
            "https://github.com/example/t3code": ARTICLE,
        }
    )
    svc, uid, session = await service(database, fetcher, FakeClock())

    # A thing with no link at all: just a name and why.
    thing = (
        await svc.save_link(
            uid, "", "omnigent", note="Try  on the\r\nshelfmark repo", queue="try"
        )
    ).item
    assert (thing.url, thing.kind, thing.copy) == (None, "thing", "none")
    assert thing.note == "Try on the\nshelfmark repo"
    # A second link-less thing must not collide on the (user_id, url) constraint.
    await svc.save_link(uid, "", "a skill", queue="try")
    with pytest.raises(LibraryError, match="name or a link"):
        await svc.save_link(uid, "  ", "", queue="try")
    with pytest.raises(LibraryError):
        await svc.save_link(uid, "", "no url", queue="saved")

    # A repo link to try is fetched like an article but is not in Saved.
    repo = (
        await svc.save_link(uid, "https://github.com/example/t3code", queue="try")
    ).item
    assert repo.copy == "extracted" and repo.saved_at is None
    assert repo.title == "example/t3code"

    # A feed item moved to To try leaves the Inbox.
    await svc.follow(uid, FEED)
    post = (await svc.items(uid, "inbox", None, None))[0]
    await svc.update(uid, post.id, trying=True)
    assert await titles(svc, uid, "inbox") == ["Other"]
    assert set(await titles(svc, uid, "try")) == {
        "omnigent",
        "a skill",
        repo.title,
        "Tool post",
    }
    assert await svc.repo.counts(uid) == {
        "inbox": 1,
        "saved": 0,
        "try": 4,
        "archive": 0,
    }

    # Archiving marks it tried; restoring returns it to To try, not the Inbox.
    await svc.update(uid, thing.id, archived=True)
    assert "omnigent" not in await titles(svc, uid, "try")
    await svc.update(uid, thing.id, archived=False)
    assert "omnigent" in await titles(svc, uid, "try")
    assert "omnigent" not in await titles(svc, uid, "inbox")

    # Adding to To try pulls an item out of Archive; removing it returns it to Inbox.
    await svc.update(uid, post.id, archived=True)
    await svc.update(uid, post.id, trying=True)
    assert "Tool post" in await titles(svc, uid, "try")
    await svc.update(uid, post.id, trying=False, note="")
    assert "Tool post" in await titles(svc, uid, "inbox")
    await session.close()
