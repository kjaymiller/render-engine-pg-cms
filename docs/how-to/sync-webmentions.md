---
title: "Sync webmentions"
description: "Pull cached webmention counts from webmention.io into the CMS — manually or via the auto-loop."
---

# Sync webmentions

For background on how webmentions reach you in the first place, see [explanation/webmention-pipeline.md](../explanation/webmention-pipeline.md).

## One-time setup

```
WEBMENTION_IO_TOKEN=<your-token>
SITE_BASE_URL=https://your-site.example
WEBMENTION_URL_TEMPLATE={base}/{type}/{slug}.html   # default; trailing-slash sites use {base}/{type}/{slug}/
```

Apply the migrations:

```bash
just load-sql sql/webmentions_migration.sql        # webmentions_count, webmentions_synced_at
just load-sql sql/webmention_types_migration.sql   # webmentions_types jsonb
```

## Sync the whole site

Three equivalent ways:

- **UI**: visit `/webmentions` → **Sync now**. Watch live progress.
- **CLI**: `just sync-webmentions`.
- **API**: `POST /webmentions/sync` (use `Accept: application/json` for automation).

Manual syncs hit every syndicated record, ignoring the age filter.

## Sync a single record

- **UI**: open the record's edit page → **Refresh count** in the syndication box.
- **API**: `POST /c/{name}/{record_id}/webmentions/sync`.

The flash message shows the breakdown:

```
Webmentions: 5 (in-reply-to:1, like:3, repost:1) · https://your-site/microblog/foo.html
```

## The auto-loop

Started on app startup. Defaults:

- Runs every `WEBMENTION_SYNC_INTERVAL` seconds (default 21600 = 6h).
- Only touches records whose `date` is within `WEBMENTION_AUTO_MAX_AGE_DAYS` days (default 60).
- Skips records that aren't syndicated (no `mastodon_url` / `bluesky_url`).

Disable it with `WEBMENTION_SYNC_INTERVAL=0`.

## Debugging "I got a reply but the count's still 0"

1. Curl webmention.io directly with the exact URL the CMS should be querying:

   ```
   curl "https://webmention.io/api/count?target=https://your-site/microblog/foo.html"
   ```

2. If that returns 0, the problem is upstream — bridgy hasn't polled yet, or the `<a class="u-syndication">` link is missing from your rendered post page.

3. If it returns >0 but the CMS reads 0, the URL in `WEBMENTION_URL_TEMPLATE` doesn't match what's been webmentioned. Mismatched template (e.g. `.html` vs trailing slash) is the #1 cause.

4. Check the rendered post HTML for `<a class="u-syndication" href="...">` pointing at the Mastodon/Bluesky copy. Without it, bridgy has no signal.
