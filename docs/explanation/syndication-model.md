---
title: "Syndication model"
description: "Why syndication URLs are stored on the record, and how that unlocks webmentions."
---

# Syndication model

Syndication isn't only about posting to Mastodon and Bluesky — it's about the *return path*. The post URLs the CMS gets back are what enable [bridgy](https://brid.gy) to backfeed interactions as webmentions.

## The chain

1. CMS posts to Mastodon / Bluesky → gets a URL back.
2. CMS stores that URL as `mastodon_url` / `bluesky_url` on the record.
3. The render-engine site's templates render those URLs as `<a class="u-syndication" href="...">` on the public post page.
4. Bridgy polls Mastodon / Bluesky, sees an interaction (like, reply, repost), and sends a webmention to webmention.io targeting the canonical post URL.
5. Webmention.io indexes it. The CMS reads the count back via its [sync loop](webmention-pipeline.md).

Without step 2, step 3 doesn't happen — without `u-syndication` markup, bridgy has no signal that the canonical post and the Mastodon/Bluesky post are the same thing.

That's why every syndication endpoint persists the returned URL: it's not just a record of "I posted there," it's the load-bearing piece that makes interactions flow back.

## The shared modal

The Publish-to-social modal is one UI for both networks because the friction of two separate flows (one button per network, two confirm dialogs) was discouraging cross-posting. Surfacing both checkboxes plus a single editable draft puts cross-posting in one keystroke.

The character counter shows the *effective* length per network — Bluesky's 300 (with rich-text URL shortening accounted for) and Mastodon's 500. Past Bluesky the highlight is subtle; past Mastodon it's stronger. Soft warnings, not hard blocks — Mastodon instances vary, and you might have a reason.

## Append-URL toggle

Whether to append the canonical post URL to a syndicated copy is genuinely contested: some readers want it, some find it noisy when the URL is already implied. The toggle defaults to off and remembers state in the form, so you make the decision per post.

When checked, the URL is appended right before submission with a blank-line separator, and only if the URL isn't already in the text — so manually typing it doesn't double up.

## Backport tool

`backport.py` exists because syndication URLs landed on records *after* the CMS had already been used. There were posts in Mastodon and Bluesky that predated `mastodon_url` / `bluesky_url`. The script walks both networks' history, matches posts back to CMS records by text + timestamp, and fills in the columns. One-shot, idempotent, dry-run by default.
