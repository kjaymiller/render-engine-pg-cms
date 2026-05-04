# render-engine-pg-cms

A lightweight FastAPI CMS for [render-engine](https://github.com/render-engine/render-engine) sites backed by the PostgreSQL collection plugin. Content types, columns, insert, and read SQL are all read from the site's `pyproject.toml` (`[tool.render-engine.pg]`) — adding a new content type to the site makes it available in the CMS automatically.

**What it does on top of basic CRUD:**
- Syndicates posts to [Mastodon](docs/how-to/syndicate-to-mastodon.md) and [Bluesky](docs/how-to/syndicate-to-bluesky.md) from a single modal, with a canonical-URL append toggle.
- Tracks [webmentions](docs/how-to/sync-webmentions.md) from bridgy with a live-progress sync log, per-type breakdown (♥ / 🔁 / 💬), and auto-refresh.
- Drag-and-drop [image uploads](docs/how-to/upload-images.md) to Azure Blob Storage with server-side resize + WebP/JPEG re-encoding.
- [AI slug and tag suggestions](docs/explanation/ai-suggestions.md) from a local Ollama server.
- [Auto-publish](docs/how-to/trigger-a-publish.md) via GitHub Actions on save, with trailing-edge debounce.

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just).

```bash
cd render-engine-pg-cms
cp .env.example .env          # set CONNECTION_STRING at minimum
just install
just dev                      # http://localhost:8000
```

## Documentation

The docs are organized by [Diátaxis](https://diataxis.fr/). Start at [docs/index.md](docs/index.md) for the full map.

**Tutorials**
- [Your first post](docs/tutorials/first-post.md) — install → write → publish.

**How-to guides**
- [Add a content type](docs/how-to/add-a-content-type.md)
- [Syndicate to Mastodon](docs/how-to/syndicate-to-mastodon.md) · [Bluesky](docs/how-to/syndicate-to-bluesky.md)
- [Sync webmentions](docs/how-to/sync-webmentions.md)
- [Upload images](docs/how-to/upload-images.md)
- [Trigger a publish](docs/how-to/trigger-a-publish.md)
- [Apply a migration](docs/how-to/apply-a-migration.md)
- [Install the extension](docs/how-to/install-the-extension.md)

**Reference**
- [Configuration (env vars)](docs/reference/configuration.md)
- [pyproject.toml schema](docs/reference/pyproject-schema.md)
- [HTTP API](docs/reference/http-api.md)
- [CLI recipes](docs/reference/cli-recipes.md)
- [Database schema](docs/reference/database-schema.md)

**Explanation**
- [Architecture](docs/explanation/architecture.md)
- [Publishing model](docs/explanation/publishing-model.md)
- [Syndication model](docs/explanation/syndication-model.md)
- [AI suggestions](docs/explanation/ai-suggestions.md)
- [Webmention pipeline](docs/explanation/webmention-pipeline.md)

## Repo layout

```
src/render_engine_pg_cms/
  main.py              FastAPI app + all routes
  config.py            env + pyproject loading
  db.py                psycopg helpers
  webmention.py        webmention.io client + sync loop
  azure_blob.py        Azure upload + URL builder
  image_optimize.py    Pillow resize + re-encode
  ollama.py            local LLM client (slug/tags)
  mastodon.py          toot API client
  bluesky.py           AT Protocol client
  github.py            workflow_dispatch trigger
  backport.py          one-off data tool
  templates/           Jinja2 views
  static/              stylesheet (hand-written, themed)
sql/                   idempotent migrations
extension/             Firefox/Zen WebExtension for quick capture
```

## Common `just` recipes

| Command                      | What it does                                         |
| ---------------------------- | ---------------------------------------------------- |
| `just install`               | `uv sync` — create venv + install deps               |
| `just dev [host] [port]`     | Run uvicorn with `--reload`                          |
| `just publish`               | Trigger the site's GitHub publish workflow           |
| `just sync-webmentions`      | Full webmention sync from the CLI (prints results)   |
| `just load-sql sql/<file>`   | Apply an idempotent migration against the DB         |
| `just backport-syndication`  | Dry-run backfill of `mastodon_url` / `bluesky_url`   |
| `just extension`             | Package the `.xpi` for Zen/Firefox                   |
| `just lock`                  | `uv lock --upgrade`                                  |

## Caveats

- No auth — run it locally or behind a private network (Tailscale works).
- Updates go through a generated `UPDATE <table> SET ... WHERE id = ...` derived from the primary INSERT's columns, since `pyproject.toml` doesn't carry explicit update SQL.
- Requires Starlette ≥ 1.0: `TemplateResponse(request, name, context)`.
