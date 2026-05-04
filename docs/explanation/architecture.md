---
title: "Architecture"
description: "How the CMS is put together and why it's pyproject-driven instead of schema-aware."
---

# Architecture

The CMS is a single FastAPI process. It owns no schema, defines no content models, and never builds pages. Everything it knows about the site comes from the site's own `pyproject.toml`. That decision is the spine of the design — almost every other choice falls out of it.

## Why `pyproject.toml` is the source of truth

Render-engine sites already declare their Postgres tables in `[tool.render-engine.pg.insert_sql]` / `[tool.render-engine.pg.read_sql]`. The build pipeline uses those statements to load static content into the DB. If the CMS duplicated that schema in its own models, the two would drift the moment you added a column.

So the CMS reads the same SQL the site does and infers the form from it. Add a column to the site → restart the CMS → the column appears in the edit form. There's no code change, no migration in this repo, no reason to keep two views in sync.

The cost: the CMS has to parse SQL well enough to learn the column list and pick a "primary insert" when multiple statements are involved (the rules are in [reference/pyproject-schema.md](../reference/pyproject-schema.md)). And there's no explicit *update* SQL — the CMS generates `UPDATE ... SET ... WHERE id = ...` from the primary INSERT's columns.

## What lives where

| File                                  | Purpose                                                |
| ------------------------------------- | ------------------------------------------------------ |
| `src/render_engine_pg_cms/main.py`    | FastAPI app + every route                              |
| `src/render_engine_pg_cms/config.py`  | Env loading + `pyproject.toml` parsing                 |
| `src/render_engine_pg_cms/db.py`      | psycopg helpers                                        |
| `src/render_engine_pg_cms/webmention.py` | webmention.io client + sync loop                    |
| `src/render_engine_pg_cms/azure_blob.py` | Azure upload + URL builder                          |
| `src/render_engine_pg_cms/image_optimize.py` | Pillow resize + re-encode                       |
| `src/render_engine_pg_cms/ollama.py`  | Local LLM client (slug/tags)                           |
| `src/render_engine_pg_cms/mastodon.py`/`bluesky.py` | API clients for syndication              |
| `src/render_engine_pg_cms/github.py`  | `workflow_dispatch` trigger                            |
| `src/render_engine_pg_cms/templates/` | Jinja2 views                                           |
| `src/render_engine_pg_cms/static/`    | Hand-written, themed CSS                               |
| `sql/`                                | Idempotent migrations for CMS-owned columns            |

## No auth

Every route — including `/api/upload` — is unauthenticated. The CMS is meant to run on localhost, or behind a private network like Tailscale. Adding auth would be a real project; the current model assumes the network already gates access.

## Image uploads

Three reasons every upload is optimized server-side:

1. **EXIF GPS leaks.** Stripping all metadata at the boundary means a casually-dropped phone photo doesn't expose your home location.
2. **Bandwidth.** A 5MB ProRAW becomes a 180KB WebP without a visible quality drop at typical web sizes.
3. **Cache forever.** Every blob has a UUID-suffixed name and `Cache-Control: public, max-age=31536000, immutable`. New uploads never invalidate anything because they have new URLs.

The `MAX_DECODE_PIXELS = 100_000_000` ceiling exists so a weaponized PNG with absurd dimensions can't blow up Pillow's memory — anything bigger passes through without decoding.

## Why FastAPI + Jinja and not a SPA

The CMS is a tool used by one person, locally, on a fast network. The thing being optimized is *time to ship a post*, not interaction polish. Server-rendered Jinja with progressive enhancement (drag-drop, AI buttons, live webmention progress, modal syndication) hits that sweet spot — every page is a static HTML response with a sprinkle of JS, no build step, no API contract to maintain between front and back.

## Background loops

Two background tasks run in the FastAPI lifespan:

- **Webmention auto-sync** (`_webmention_sync_loop`) — see [explanation/webmention-pipeline.md](webmention-pipeline.md).
- **Auto-publish debouncer** — per-record `asyncio.Task` cancelled and re-scheduled on each save. See [explanation/publishing-model.md](publishing-model.md).

Both are deliberately simple: no Celery, no Redis, no external queue. Restarting the process loses any in-flight debounce timer, but a re-save re-arms it.
