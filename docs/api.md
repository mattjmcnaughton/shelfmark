# API Reference

All `/api/*` endpoints require a signed-in user and return JSON. Errors use
FastAPI's shape, `{"detail": "Human-readable message."}`, which the desk shows
as-is. Mutating requests must send `Content-Type: application/json` and come from
the same site (cross-site `Sec-Fetch-Site` or a foreign `Origin` gets 403).

## Health

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/healthz` | Liveness probe, no auth |
| GET | `/readyz` | Readiness probe (database reachable), no auth |

## Auth

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/auth/signin?returnTo=/` | Starts Sign in with Auth0 (302 to the Auth0 tenant). Only with the `auth0` provider. |
| GET | `/auth/callback` | OAuth redirect URI. |
| POST | `/auth/signout` | Clears the session, 303 to Auth0 `/v2/logout`, which returns to `/`. |

Without a session, `/api/*` returns 401 with
`{"detail": "Sign in to continue.", "sign_in_url": "/auth/signin"}`.
A signed-in account that is not allowed gets 403 with a `detail` naming its user ID.
When production auth is not configured, `/api/*` returns 503 (fail closed).

## Library

`GET /api/library`

```json
{
  "user": {"name": "Matt", "can_sign_out": true},
  "feeds": [{"id": 1, "url": "https://example.com/feed", "title": "Example",
             "checked_at": "2026-11-21T02:00:00Z", "error": null}],
  "tags": ["design", "later"],
  "counts": {"inbox": 12, "saved": 3, "try": 4, "archive": 40}
}
```

## Items

An **item summary**:

```json
{
  "id": 7, "url": "https://example.com/post", "kind": "article",
  "title": "A post", "source": "Example", "author": "Ada", "deck": "Short excerpt",
  "video_id": null, "published_at": "2026-11-20T12:00:00Z",
  "saved": false, "archived": false, "note": "",
  "tags": ["design"], "feed_ids": [1], "copy": "feed"
}
```

`kind` is `article`, `video`, or `thing`. A `thing` is something to try (a tool,
repo, skill, or idea): a name, an optional link (`url` is `null` without one), a short
description in `deck`, a note, and tags. Things are link aggregation, not reading:
their link is never extracted as an article, and they are separate from reading
items, so the same URL can be both a saved article and a thing to try. `video_id` is an
11-character YouTube ID for videos. `copy` says where the reading text came from:
`feed` (feed entry content), `extracted` (clean article extraction, also used for
feed entries that carry only a summary), `link`
(nothing readable; show the original-link fallback), or `none` (no link at all).
`note` is the user's own plain-text note, such as why something is worth trying.
An **item detail** adds `body`, a list of plain-text blocks
`[{"text": "…", "heading": false}]`. Bodies never contain HTML.

| Method | Path | Body | Result |
| ------ | ---- | ---- | ------ |
| GET | `/api/items?view=inbox` | | `{"items": [summary…]}` |
| GET | `/api/items?view=saved` | | Saved, not archived |
| GET | `/api/items?view=try` | | To try, not archived |
| GET | `/api/items?view=archive` | | Archived |
| GET | `/api/items?view=feed&feed_id=1` | | Entries of a feed, not archived |
| GET | `/api/items?view=tag&tag=design` | | Items with the tag, archived included |
| GET | `/api/items/{id}` | | detail |
| POST | `/api/items` | `{"url": "…", "title": "optional", "note": "optional", "queue": "saved"}` | 201 detail; saves a link (article or YouTube) to Saved. A known URL is added to the queue and unarchived (200). |
| POST | `/api/items` | `{"queue": "try", "title": "omnigent", "url": "optional", "description": "optional", "note": "optional", "tags": ["optional"]}` | 201 detail; adds a thing to try. Needs a `url` or a `title`. Without a `title`, the page's title and description fill in the name and description. A link already in To try is returned (200), unarchived, with the new tags merged in. |
| PATCH | `/api/items/{id}` | any of `{"saved": bool, "archived": bool, "tags": ["…"], "note": "…"}` | detail; `saved: true` on a thing is 400 |

Queues: **Inbox** is feed triage: reading items that are not saved and not
archived. **Saved** is the deliberate reading queue. **To try** holds the things to
try; reading items are never moved into it. Saving an archived item unarchives it.
Archiving a thing means it was tried. Restoring (`archived: false`) returns a thing
to To try, a saved item to Saved, and anything else to the Inbox. Lists are newest first (`published_at`, then
`id`), capped at 500. Notes are at most 2000 characters.

## Feeds

| Method | Path | Body | Result |
| ------ | ---- | ---- | ------ |
| POST | `/api/feeds` | `{"url": "…", "title": "optional"}` | 201 feed; imports the latest `feed_backfill` entries. 409 when already followed. |
| POST | `/api/feeds/refresh` | `{}` | `{"feeds": [feed…]}`; per-feed failures are in each feed's `error`. |

`url` may be an RSS or Atom feed, a web page that advertises one with
`<link rel="alternate">`, a YouTube channel URL (`/channel/UC…`, `/@handle`,
`/c/…`, `/user/…`), or a bare YouTube `@handle`. Following imports only the newest
`feed_backfill` entries; the older entries the feed lists at that moment are
remembered and never imported, while every later entry is. A feed entry that has
only a short summary gets its full article fetched and extracted; if that fails,
the summary is kept.

The server also refreshes every user's feeds in the background
(`SHELFMARK_REFRESH_MINUTES`, default 20; 0 disables).

## Settings

| Method | Path | Body | Result |
| ------ | ---- | ---- | ------ |
| GET | `/api/settings` | | `{"feed_backfill": 3}` |
| PATCH | `/api/settings` | `{"feed_backfill": 0..60}` | settings; 400 outside the range |

Settings are stored per user. `feed_backfill` (default 3) is how many of a newly
followed feed's latest entries to import.
