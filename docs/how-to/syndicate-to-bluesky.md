---
title: "Syndicate a post to Bluesky"
description: "Cross-post a microblog or blog record to Bluesky via the AT Protocol."
---

# Syndicate a post to Bluesky

## One-time setup

Set these in `.env`:

```
BLUESKY_HANDLE=you.bsky.social
BLUESKY_APP_PASSWORD=<app-password>
BLUESKY_PDS=https://bsky.social     # optional, default
SITE_BASE_URL=https://your-site.example
```

Create an app password at **Bluesky Settings → App Passwords** (don't use your account password). `SITE_BASE_URL` is needed so relative `image_url` values resolve.

Apply the migration:

```bash
just load-sql sql/bluesky_migration.sql
```

## Posting

1. Edit any `microblog` or `blog` record.
2. **Publish to social** → tick **Bluesky**.
3. Watch the character counter — Bluesky's limit is 300 (rich-text shortens URLs, so the counter shows the *effective* length).
4. **Submit**.

The returned `at://` URL is converted to `https://bsky.app/profile/...` and saved as `bluesky_url`.

## Posting via API

```bash
curl -X POST http://localhost:8000/c/microblog/42/bluesky \
  -d "status=Hello from the CMS"
```

## Backfilling

`just backport-syndication` also matches Bluesky history — see [the Mastodon how-to](syndicate-to-mastodon.md#backfilling-old-posts).

## When it fails

| Error                          | Likely cause                                  |
| ------------------------------ | --------------------------------------------- |
| `401 Unauthorized`             | App password wrong, or handle/PDS mismatch.   |
| `Post too long`                | Exceeds 300 chars after rich-text expansion.  |
| `Media upload failed`          | Image too large or unreachable from `SITE_BASE_URL`. |
