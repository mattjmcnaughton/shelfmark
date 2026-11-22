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
  "saved": false, "trying": false, "archived": false, "note": "",
  "tags": ["design"], "feed_ids": [1], "copy": "feed"
}
```

`kind` is `article`, `video`, or `thing`. A `thing` is something to try that has no
link (just a name and a note), so its `url` is `null`. `video_id` is an
11-character YouTube ID for videos. `copy` says where the reading text came from:
`feed` (feed entry content), `extracted` (clean article extraction), `link`
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
| POST | `/api/items` | `{"queue": "try", "title": "omnigent", "url": "optional", "note": "optional"}` | 201 detail; adds something to try. Needs a `url` or a `title`. With a link it is fetched and extracted like a saved link. |
| PATCH | `/api/items/{id}` | any of `{"saved": bool, "trying": bool, "archived": bool, "tags": ["…"], "note": "…"}` | detail |

Queues: **Inbox** is feed triage: items that are not saved, not to try, and not
archived. **Saved** is the deliberate reading queue. **To try** holds tools, repos,
skills, and ideas to try out later. An item can be in Saved and To try at once.
Adding an archived item to Saved or To try unarchives it. Archiving a to-try item
means it was tried. Restoring (`archived: false`) returns an item to the queues it
is in, or to Inbox if it is in none. Lists are newest first (`published_at`, then
`id`), capped at 500. Notes are at most 2000 characters.

## Feeds

| Method | Path | Body | Result |
| ------ | ---- | ---- | ------ |
| POST | `/api/feeds` | `{"url": "…", "title": "optional"}` | 201 feed; fetches and imports recent entries. 409 when already followed. |
| POST | `/api/feeds/refresh` | `{}` | `{"feeds": [feed…]}`; per-feed failures are in each feed's `error`. |

The server also refreshes every user's feeds in the background
(`SHELFMARK_REFRESH_MINUTES`, default 20; 0 disables).
