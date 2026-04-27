---
title: "Syndication (Mastodon + Bluesky)"
description: "From the edit page for any `microblog` or `blog` record, you can cross-post to Mastodon and/or Bluesky in one step. The CMS stores the returned post URLs back on the record (`mastodon_url`, `bluesky_url`) — those URLs become the `u-syndication` hints on the public site, which is what lets [bridgy backfeed webmentions](webmentions.md)."
---

# Syndication (Mastodon + Bluesky)

From the edit page for any `microblog` or `blog` record, you can cross-post to Mastodon and/or Bluesky in one step. The CMS stores the returned post URLs back on the record (`mastodon_url`, `bluesky_url`) — those URLs become the `u-syndication` hints on the public site, which is what lets [bridgy backfeed webmentions](webmentions.md).

## The Publish-to-social modal

Click **Publish to social** on the edit page (appears only when a record isn't already syndicated to at least one network). The modal contains:

- **Target checkboxes**: Mastodon and Bluesky, each with a character-limit hint (`max 500` / `max 300`). Already-posted targets are disabled.
- **Draft textarea**: pre-populated with `build_status_text(ct.name, record, tags)`. Live character counters show the *effective* length — including the canonical URL if you have the append toggle checked.
- **Highlight overlay**: characters past the Bluesky limit get a subtle warning, past the Mastodon limit a stronger warning.
- **Attached image chip**: shows the first image the CMS finds on the record (`image_url`, `feature_image`, or derived).
- **Append post URL** checkbox: when checked, the canonical URL (built from `WEBMENTION_URL_TEMPLATE`) is concatenated to the draft with a blank-line separator right before submission. Skipped if the URL is already in the text.
- **Submit**: posts to `/c/{name}/{id}/syndicate` with the selected targets.

## Handlers

Three POST endpoints share logic via a common sender:

| Endpoint                                 | Target                        |
| ---------------------------------------- | ----------------------------- |
| `/c/{name}/{id}/mastodon`                | Mastodon only                 |
| `/c/{name}/{id}/bluesky`                 | Bluesky only                  |
| `/c/{name}/{id}/syndicate`               | Both (checkboxes pick which)  |

Each handler:

1. Reads the record from Postgres.
2. Posts to the network via `mastodon.post_status` / `bluesky.post_status`.
3. Stores the returned URL via `db.set_mastodon_url` / `db.set_bluesky_url`.
4. Redirects with a flash message.

## Image handling

- Mastodon: single image attached as media; alt text is `record.image_alt` or inferred.
- Bluesky: single image uploaded as a blob, wired into the post's `embed.images`.

If the record has no image, posts go out text-only on both networks.

## Character limits

Hard-coded in `main.py`:

- Mastodon: 500
- Bluesky: 300

If the draft exceeds the limit, the submit-time confirm dialog warns you — individual senders will pass through whatever you send, so confirm twice if you want to exceed them deliberately (some Mastodon instances allow longer, and Bluesky rich-text includes URL-shortening).

## Env vars

See [configuration.md](configuration.md#mastodon) and [configuration.md](configuration.md#bluesky).

## Backfill

`backport.py` (run via `just backport-syndication` dry / `apply`) walks Mastodon and Bluesky history, matches posts back to CMS records by text + timestamp, and fills in missing `mastodon_url` / `bluesky_url`. One-time tool.

## Common failure modes

| Error                                         | Cause                                              |
| --------------------------------------------- | -------------------------------------------------- |
| `Missing MASTODON_ACCESS_TOKEN / INSTANCE`    | Env vars unset or empty.                           |
| `401 Unauthorized` (Bluesky)                  | App password wrong, or handle/PDS mismatch.        |
| `Post too long`                               | Exceeds network limit — truncate and retry.        |
| `Media upload failed`                         | Image URL unreachable or over network's size cap.  |
