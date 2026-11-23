"""LibraryService against a real database with a fake fetcher and clock."""

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


async def test_to_try_holds_things_apart_from_reading_items(database):
    repo_url = "https://github.com/example/t3code"
    repo_page = ARTICLE.replace(
        "<head>", '<head><meta name="description" content="A coding agent UI.">'
    )
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
            ),
            repo_url: repo_page,
        }
    )
    svc, uid, session = await service(database, fetcher, FakeClock())

    # A thing with no link at all: just a name and why.
    thing = (
        await svc.add_thing(uid, "omnigent", note="Try  on the\r\nshelfmark repo")
    ).item
    assert (thing.url, thing.kind, thing.copy) == (None, "thing", "none")
    assert thing.note == "Try on the\nshelfmark repo"
    # A second link-less thing must not collide on the (user_id, url) index.
    await svc.add_thing(uid, "a skill")
    with pytest.raises(LibraryError, match="name or a link"):
        await svc.add_thing(uid, " ", "  ")

    # A named link with labels is kept as a link: nothing is fetched or extracted.
    named = (
        await svc.add_thing(
            uid,
            "T3 Code",
            repo_url,
            description="Theo's agent UI",
            tags=["Agents", "agents", "UI"],
        )
    ).item
    assert repo_url not in fetcher.fetched
    assert (named.kind, named.copy, named.body, named.saved_at) == (
        "thing",
        "link",
        [],
        None,
    )
    assert (named.title, named.deck, named.source) == (
        "T3 Code",
        "Theo's agent UI",
        "github.com",
    )
    assert [t.name for t in named.tags] == ["agents", "ui"]

    # Adding the same link again returns the same thing and merges labels.
    again = await svc.add_thing(uid, "", repo_url, tags=["later"])
    assert not again.created and again.item.id == named.id
    assert again.item.title == "T3 Code"
    assert [t.name for t in again.item.tags] == ["agents", "later", "ui"]

    # The same link can also be a saved article, separate from the thing.
    article = (await svc.save_link(uid, repo_url)).item
    assert article.id != named.id and article.kind == "article"
    assert await titles(svc, uid, "saved") == ["example/t3code"]

    # Without a name, the page fills in the name and description, but no body.
    await svc.update(uid, named.id, archived=True)
    other = "https://github.com/example/other"
    fetcher.pages[other] = repo_page
    unnamed = (await svc.add_thing(uid, "", other)).item
    assert (unnamed.title, unnamed.deck) == ("example/other", "A coding agent UI.")
    assert unnamed.body == [] and unnamed.copy == "link"

    # Things to try cannot be saved, and feed items cannot be put in To try.
    with pytest.raises(LibraryError, match="stay in To try"):
        await svc.update(uid, thing.id, saved=True)
    await svc.follow(uid, FEED)
    assert await titles(svc, uid, "inbox") == ["Tool post"]
    assert set(await titles(svc, uid, "try")) == {
        "omnigent",
        "a skill",
        "example/other",
    }
    assert await svc.repo.counts(uid) == {
        "inbox": 1,
        "saved": 1,
        "try": 3,
        "archive": 1,
    }

    # Archiving marks it tried; restoring returns it to To try, not the Inbox.
    await svc.update(uid, thing.id, archived=True)
    assert "omnigent" not in await titles(svc, uid, "try")
    await svc.update(uid, thing.id, archived=False)
    assert "omnigent" in await titles(svc, uid, "try")
    assert "omnigent" not in await titles(svc, uid, "inbox")
    # Adding a tried thing's link again brings it back to To try.
    assert (await svc.add_thing(uid, "", repo_url)).item.archived_at is None
    await session.close()


def dated(n: int) -> tuple[str, str, str, str]:
    return (
        f"Post {n}",
        f"https://blog.example.com/{n}",
        f"{n:02d} Nov 2026 09:00:00 GMT",
        f"<p>Teaser {n}</p>",
    )


async def test_following_imports_only_the_latest_posts_from_the_setting(database):
    # Out of date order, so taking the first entries would pick the wrong ones.
    fetcher = FakeFetcher({FEED: rss("B", *(dated(n) for n in (3, 5, 1, 4, 2)))})
    clock = FakeClock()
    svc, uid, session = await service(database, fetcher, clock)
    assert (await svc.settings(uid)).feed_backfill == 3

    feed = await svc.follow(uid, FEED)
    assert await titles(svc, uid, "inbox") == ["Post 5", "Post 4", "Post 3"]

    # A refresh imports new posts, never the older ones skipped at follow time.
    fetcher.pages[FEED] = rss("B", *(dated(n) for n in (6, 5, 4, 3, 2, 1)))
    clock.advance(minutes=20)
    await svc.refresh_feed(feed)
    assert await titles(svc, uid, "feed", feed_id=feed.id) == [
        "Post 6",
        "Post 5",
        "Post 4",
        "Post 3",
    ]

    # The setting is per user and stored; 0 follows from the next new post on.
    with pytest.raises(LibraryError, match="0 to 60"):
        await svc.update_settings(uid, feed_backfill=61)
    await svc.update_settings(uid, feed_backfill=0)
    assert (await svc.settings(uid)).feed_backfill == 0
    second = "https://other.example.com/feed"
    fetcher.pages[second] = rss("Other", ("Old", "https://other.example.com/o", "", ""))
    other = await svc.follow(uid, second)
    assert await titles(svc, uid, "feed", feed_id=other.id) == []
    fetcher.pages[second] = rss(
        "Other",
        ("New", "https://other.example.com/n", "", ""),
        ("Old", "https://other.example.com/o", "", ""),
    )
    await svc.refresh_feed(other)
    assert await titles(svc, uid, "feed", feed_id=other.id) == ["New"]
    await session.close()


async def test_summary_only_feed_entries_fetch_the_full_article(database):
    long_post = "<p>" + "Every word of the post is in the feed. " * 30 + "</p>"
    fetcher = FakeFetcher(
        {
            FEED: rss(
                "B",
                (
                    "Teaser",
                    "https://blog.example.com/full",
                    "Fri, 20 Nov 2026 09:00:00 GMT",
                    "<p>A short summary.</p>",
                ),
                (
                    "Unreachable",
                    "https://blog.example.com/gone",
                    "Thu, 19 Nov 2026 09:00:00 GMT",
                    "<p>Only the summary.</p>",
                ),
                (
                    "Whole",
                    "https://blog.example.com/whole",
                    "Wed, 18 Nov 2026 09:00:00 GMT",
                    long_post,
                ),
            ),
            "https://blog.example.com/full": ARTICLE,
        }
    )
    svc, uid, session = await service(database, fetcher, FakeClock())
    await svc.follow(uid, FEED)
    by_title = {i.title: i for i in await svc.items(uid, "inbox", None, None)}

    teaser = by_title["Teaser"]
    assert teaser.copy == "extracted" and teaser.deck == "A short summary."
    assert "attention compounds" in " ".join(str(b["text"]) for b in teaser.body)
    assert teaser.author == "Ada Lovelace"
    # When the article cannot be fetched, the feed's summary is still there.
    gone = by_title["Unreachable"]
    assert gone.copy == "feed"
    assert gone.body == [{"text": "Only the summary.", "heading": False}]
    # An entry whose feed carries the whole post is not fetched again.
    assert by_title["Whole"].copy == "feed"
    assert "https://blog.example.com/whole" not in fetcher.fetched
    await session.close()


async def test_following_a_site_page_finds_its_feed(database):
    home = (
        '<!doctype html><html><head><link rel="alternate" '
        'type="application/rss+xml" href="/feed"></head><body>Hi</body></html>'
    )
    fetcher = FakeFetcher(
        {
            "https://blog.example.com/": home,
            "https://blog.example.com/feed": rss("Blog", dated(1)),
        }
    )
    svc, uid, session = await service(database, fetcher, FakeClock())
    feed = await svc.follow(uid, "https://blog.example.com")
    assert feed.url == "https://blog.example.com/feed" and feed.title == "Blog"
    fetcher.pages["https://plain.example.com/"] = "<!doctype html><p>No feed</p>"
    with pytest.raises(LibraryError, match="valid RSS or Atom"):
        await svc.follow(uid, "https://plain.example.com/")
    await session.close()
