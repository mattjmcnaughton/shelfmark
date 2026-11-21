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
| GET | `/auth/signin?returnTo=/` | Starts Sign in with Amp (302 to Amp). Only with the `amp` provider. |
| GET | `/auth/callback` | OAuth redirect URI. |
| POST | `/auth/signout` | Clears the session, 303 to `/`. |

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
  "counts": {"inbox": 12, "saved": 3, "archive": 40}
}
```

## Items

An **item summary**:

```json
{
  "id": 7, "url": "https://example.com/post", "kind": "article",
  "title": "A post", "source": "Example", "author": "Ada", "deck": "Short excerpt",
  "video_id": null, "published_at": "2026-11-20T12:00:00Z",
  "saved": false, "archived": false, "tags": ["design"], "feed_ids": [1],
  "copy": "feed"
}
```

`kind` is `article` or `video`. `video_id` is an 11-character YouTube ID for videos.
`copy` says where the reading text came from: `feed` (feed entry content),
`extracted` (clean article extraction), or `link` (nothing readable; show the
original-link fallback). An **item detail** adds `body`, a list of plain-text
blocks `[{"text": "…", "heading": false}]`. Bodies never contain HTML.

| Method | Path | Body | Result |
| ------ | ---- | ---- | ------ |
| GET | `/api/items?view=inbox` | | `{"items": [summary…]}` |
| GET | `/api/items?view=saved` | | Saved, not archived |
| GET | `/api/items?view=archive` | | Archived |
| GET | `/api/items?view=feed&feed_id=1` | | Entries of a feed, not archived |
| GET | `/api/items?view=tag&tag=design` | | Items with the tag, archived included |
| GET | `/api/items/{id}` | | detail |
| POST | `/api/items` | `{"url": "…", "title": "optional"}` | 201 detail; saves a link (article or YouTube). Saving a known URL marks it saved and unarchives it (200). |
| PATCH | `/api/items/{id}` | any of `{"saved": bool, "archived": bool, "tags": ["…"]}` | detail |

Views: **Inbox** is unsaved, unarchived items (feed triage). **Saved** is the
deliberate queue. Saving an archived item unarchives it. Restoring an archived
item (`archived: false`) returns it to Saved if it is saved, otherwise to Inbox.
Lists are newest first (`published_at`, then `id`), capped at 500.

## Feeds

| Method | Path | Body | Result |
| ------ | ---- | ---- | ------ |
| POST | `/api/feeds` | `{"url": "…", "title": "optional"}` | 201 feed; fetches and imports recent entries. 409 when already followed. |
| POST | `/api/feeds/refresh` | `{}` | `{"feeds": [feed…]}`; per-feed failures are in each feed's `error`. |

The server also refreshes every user's feeds in the background
(`SHELFMARK_REFRESH_MINUTES`, default 20; 0 disables).
