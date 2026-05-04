---
title: "Your first post"
description: "End-to-end walkthrough: install the CMS, point it at a render-engine site's database, write a microblog post, and publish it."
---

# Your first post

This tutorial takes you from a fresh checkout to a published post. By the end, you'll have written a microblog entry, syndicated it (optionally), and triggered a deploy.

## What you need

- An existing [render-engine](https://github.com/render-engine/render-engine) site with a PostgreSQL collection plugin already configured (the CMS reads its `pyproject.toml`).
- [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just) installed.
- The DSN for the same Postgres database the site uses.

## 1. Clone and install

```bash
git clone https://github.com/kjaymiller/render-engine-pg-cms.git
cd render-engine-pg-cms
cp .env.example .env
just install
```

## 2. Configure

Open `.env` and set, at minimum:

```
CONNECTION_STRING=postgresql://user:pass@host/db
SITE_PYPROJECT=/absolute/path/to/your-site/pyproject.toml
```

Everything else (syndication, uploads, AI) is optional and layered on later. See [reference/configuration.md](../reference/configuration.md) for every variable.

## 3. Apply migrations

The CMS adds a few columns to the site's tables (syndication URLs, webmention counts). Run them once:

```bash
just load-sql sql/mastodon_migration.sql
just load-sql sql/bluesky_migration.sql
just load-sql sql/webmentions_migration.sql
just load-sql sql/webmention_types_migration.sql
```

They're all `IF NOT EXISTS`-guarded — safe to re-run.

## 4. Start the CMS

```bash
just dev
```

Open <http://localhost:8000>. You'll see a unified timeline (empty for now) and a masthead with one nav entry per content type detected from your site's `pyproject.toml`.

## 5. Write a post

1. Click `microblog` in the masthead (or whichever short-form type your site has).
2. Click **New**.
3. Fill in `content`. Notice that as you type a `title` (if your type has one), the `slug` field auto-populates.
4. Click the sparkle next to `slug` for an AI suggestion (requires Ollama — skip if you haven't set it up).
5. Drag an image onto the `content` textarea to upload + insert a markdown link (requires Azure Blob — skip if not configured).
6. Click **Save**.

You're redirected to the list view with a flash message confirming the save.

## 6. Publish

If `GITHUB_TOKEN` and `GITHUB_REPO` are set, the CMS already scheduled a publish — debounced 60s after your last save. Wait, or click **Publish** in the masthead to fire one immediately.

To verify, check the GitHub Actions tab on your site repo: a `workflow_dispatch` run should appear.

## 7. (Optional) Syndicate

On the post's edit page, click **Publish to social**. Tick Mastodon and/or Bluesky, edit the draft, and submit. The returned post URLs are saved on the record — and that's what unlocks bridgy-backfed [webmentions](../explanation/webmention-pipeline.md).

## What's next

- Wire up [syndication](../how-to/syndicate-to-mastodon.md) and [uploads](../how-to/upload-images.md) properly.
- Read [the architecture explanation](../explanation/architecture.md) to understand how the CMS stays schema-less.
- Skim the [HTTP API reference](../reference/http-api.md) if you want to drive it from scripts.
