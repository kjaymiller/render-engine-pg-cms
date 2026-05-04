---
title: "Webmention pipeline"
description: "How interactions on Mastodon and Bluesky reach the CMS and become cached counts."
---

# Webmention pipeline

The CMS doesn't receive webmentions directly. It caches counts that webmention.io has already indexed, which were sent to it by [bridgy](https://brid.gy), which got them from Mastodon and Bluesky. Each link in that chain matters.

## Why caching, not live fetching

The site's public post pages render webmention chips ("♥ 12 · 🔁 3 · 💬 2") inline. If those numbers required a webmention.io fetch on every page render, the site would be slow and rate-limited. So the CMS pulls the counts on a schedule and writes them back to Postgres. The render-engine templates then read from the database — no client-side fetch, no deploy-time API call.

The trade-off: counts can be up to `WEBMENTION_SYNC_INTERVAL` (default 6h) stale. For a personal site, that's fine. The auto-loop plus a manual **Sync now** button covers both the steady state and "I want to see this *now*."

## The age filter

`WEBMENTION_AUTO_MAX_AGE_DAYS` (default 60) restricts the auto-loop to records whose `date` is within the last N days. Old posts rarely pick up new mentions; polling them every 6 hours wastes API calls.

Manual syncs ignore the age filter — if you specifically asked for a full sync, you presumably want every record refreshed.

## Startup-stampede avoidance

Restarting the server 10 minutes after a sync shouldn't immediately re-poll webmention.io. So the loop reads `MAX(webmentions_synced_at)` across the syndicated tables and waits `max(0, interval - elapsed)` before the first run. A restart inside the interval is essentially a no-op.

## Target filter

Records without a slug, or without at least one of `mastodon_url` / `bluesky_url`, can't have received bridgy-backfed mentions. So the loop's WHERE clause excludes them up front. This is more than a perf optimization — it keeps the **changed/new** counts in the live UI honest.

## Per-record granularity

The `/webmentions` page polls `GET /webmentions/status?since=N` rather than re-fetching the whole status object. As records are processed, the server appends them to a `new` array; the client passes the highest index it's seen as `since`, and only gets back the deltas. This is what lets the UI animate rows in (scarlet → sage flash) one at a time as a sync runs.

## When the count's wrong

The most common problem: the CMS is querying webmention.io with one URL while bridgy webmentioned a different one. The `WEBMENTION_URL_TEMPLATE` env var has to match exactly the URL render-engine produces. `.html` vs trailing slash matters; protocol matters; subdomain matters.

The [how-to](../how-to/sync-webmentions.md#debugging-i-got-a-reply-but-the-counts-still-0) walks through the debugging steps. The short version: curl webmention.io directly with the URL the CMS would use; if it returns 0, fix bridgy or the `u-syndication` markup; if it returns >0, fix the template.
