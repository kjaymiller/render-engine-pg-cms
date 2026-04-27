---
title: "Webmentions"
description: "The CMS caches webmention counts (and per-type breakdowns) from [webmention.io](https://webmention.io/) so the site can render them cheaply and you can see interaction activity in the admin UI."
---

# Webmentions

The CMS caches webmention counts (and per-type breakdowns) from [webmention.io](https://webmention.io/) so the site can render them cheaply and you can see interaction activity in the admin UI.

**Everything here assumes bridgy is your mention source.** If you also receive direct webmentions (e.g. from other IndieWeb blogs), the sync still works — it just reads whatever webmention.io has indexed for each target URL.

## End-to-end flow

1. You publish a post on the site with `<a class="u-syndication">` links to the Mastodon/Bluesky syndicated copies (the render-engine templates render these automatically when `mastodon_url` / `bluesky_url` are set).
2. [brid.gy](https://brid.gy) polls the Mastodon/Bluesky posts for interactions.
3. For each interaction, bridgy sends a webmention to webmention.io targeting your canonical post URL.
4. webmention.io indexes it. Count goes up; type dict (`like`, `repost`, `in-reply-to`, …) updates.
5. The CMS's auto-loop polls webmention.io's count API for each syndicated post and writes the results back to the DB.
6. The public site renders the cached counts as chips without any client-side fetch.

## Database columns

Run these migrations once:

```
just load-sql sql/webmentions_migration.sql       # webmentions_count, webmentions_synced_at
just load-sql sql/webmention_types_migration.sql  # webmentions_types jsonb
```

Each applies to both `microblog` and `blog`.

| Column                    | Type            | Meaning                                           |
| ------------------------- | --------------- | ------------------------------------------------- |
| `webmentions_count`       | `integer`       | Total mentions (all types combined).              |
| `webmentions_synced_at`   | `timestamptz`   | When the row was last refreshed.                  |
| `webmentions_types`       | `jsonb`         | Per-type breakdown, e.g. `{"like":3,"repost":1}`. |

## Canonical URL template

The sync queries webmention.io using the canonical URL of each post, built from `WEBMENTION_URL_TEMPLATE`:

```
{base}/{type}/{slug}.html
```

- `{base}` = `SITE_BASE_URL` (no trailing slash).
- `{type}` = content type name.
- `{slug}` = record slug.

If your site serves posts at trailing-slash URLs, override:

```
WEBMENTION_URL_TEMPLATE="{base}/{type}/{slug}/"
```

A mismatched template is the #1 cause of "I got a reply but the count's still 0."

## Auto-sync loop

Started on app startup (`lifespan`), managed by `_webmention_sync_loop` in `main.py`. Behavior:

- **Interval**: `WEBMENTION_SYNC_INTERVAL` seconds (default `21600` = 6h).
- **Startup stampede avoidance**: looks at `MAX(webmentions_synced_at)` across tables. If a sync happened `T` seconds ago, waits `max(0, interval - T)` before the first run — restarting the server 10 minutes after a sync doesn't immediately re-poll webmention.io.
- **Age filter**: `WEBMENTION_AUTO_MAX_AGE_DAYS` (default `60`). The auto-loop only touches records whose `date` is within the last N days — old posts rarely pick up new mentions. Set to `0` to disable the filter.
- **Target filter**: always `WHERE slug IS NOT NULL AND (mastodon_url IS NOT NULL OR bluesky_url IS NOT NULL)`. Records that were never syndicated can't receive bridgy-backfed mentions, so skipping them is free savings.
- **Error resilience**: per-record errors are caught and logged into that record's `error` field; the loop continues. TCP keepalives on every DB connection, 3-attempt retry with backoff on both the DB connect and webmention.io fetch.
- **Disable**: `WEBMENTION_SYNC_INTERVAL=0`.

## Manual sync

### Whole site

- **UI**: `/webmentions` → **Sync now** button. Runs an async task, shows live progress.
- **API**: `POST /webmentions/sync`. Accepts `Accept: application/json` for automation.
- **CLI**: `just sync-webmentions`.

Manual syncs ignore `WEBMENTION_AUTO_MAX_AGE_DAYS` — they hit every syndicated record.

### Single record

- **UI**: edit page syndication box → **Refresh count** button (appears when the record has a slug + at least one syndicated URL).
- **API**: `POST /c/{name}/{record_id}/webmentions/sync`.

Flash message after a per-record sync shows the breakdown:
`Webmentions: 5 (in-reply-to:1, like:3, repost:1) · https://kjaymiller.com/microblog/foo.html`

## The /webmentions page

- **Status card**: live stats — running, processed/total, changed, failed, last-update timestamp.
- **Progress bar**: fills left-to-right as records complete during a live sync.
- **Log table**: every synced record with prev → new → delta → per-type chips → status. Rows with new mentions flash scarlet → sage; errors stay scarlet.
- **Polling cadence**: 1.5s while a sync is running, 5s when idle. Uses `GET /webmentions/status?since=N` so each poll only ships the records that appeared since the last fetch.

## Masthead indicator

A small pill in the masthead (on every page) polls `/webmentions/status` and:

- Shows **wm · +N** when N new changes landed in the last sync.
- Shows **syncing 12/87** with a spinning icon when a sync is live.
- Links to `/webmentions` for the full log.

## Sanity-checking

If a post you expect has mentions but shows 0:

1. Curl webmention.io directly with the exact URL the CMS is using:
   ```
   curl "https://webmention.io/api/count?target=https://kjaymiller.com/microblog/foo.html"
   ```
2. If that returns 0, the problem is upstream (bridgy not polling, `u-syndication` missing from the rendered page, etc.).
3. If it returns >0 but the CMS shows 0, check `WEBMENTION_URL_TEMPLATE` — the CMS might be querying a different URL than you just tested.
4. Inspect the rendered post page HTML for `<a class="u-syndication" ...>` pointing at the Mastodon/Bluesky copy. Missing `u-syndication` → bridgy has no signal.

## Related config

See [configuration.md](configuration.md#webmentions-webmentionio--bridgy).
