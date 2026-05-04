---
title: "Syndicate a post to Mastodon"
description: "Cross-post a microblog or blog record to Mastodon and store the returned URL on the record."
---

# Syndicate a post to Mastodon

## One-time setup

Set these in `.env`:

```
MASTODON_INSTANCE=https://mastodon.social
MASTODON_ACCESS_TOKEN=<token-with-write:statuses>
MASTODON_VISIBILITY=public        # optional: unlisted | private | direct
```

Generate a token in Mastodon → **Preferences → Development → New application**. Scope: `write:statuses` (and `write:media` if you syndicate images).

Apply the migration that adds `mastodon_url`:

```bash
just load-sql sql/mastodon_migration.sql
```

## Posting from the edit page

1. Open any `microblog` or `blog` record's edit page.
2. Click **Publish to social**.
3. Tick **Mastodon**.
4. Edit the draft (pre-filled from the record). Watch the live character counter — Mastodon's limit is 500.
5. Optionally tick **Append post URL** to add the canonical URL on a new line at the end.
6. Click **Submit**.

The returned URL is saved as `mastodon_url` on the record. That URL is what your render-engine templates expose as `<a class="u-syndication">` — which is what enables [bridgy-backfed webmentions](../explanation/webmention-pipeline.md).

## Posting via API

```bash
curl -X POST http://localhost:8000/c/microblog/42/mastodon \
  -d "status=Hello from the CMS"
```

See [reference/http-api.md](../reference/http-api.md#syndication).

## Backfilling old posts

If you have Mastodon posts that predate the CMS, run:

```bash
just backport-syndication       # dry-run
just backport-syndication apply # apply
```

It walks Mastodon history, matches posts to records by text + timestamp, and fills in `mastodon_url`. One-shot tool.

## When it fails

| Error                                      | Likely cause                                |
| ------------------------------------------ | ------------------------------------------- |
| `Missing MASTODON_ACCESS_TOKEN / INSTANCE` | Env var unset.                              |
| `Post too long`                            | Exceeds 500 chars (some instances allow more — confirm twice in the dialog). |
| `Media upload failed`                      | Image URL unreachable or over Mastodon's size cap. |
