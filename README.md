# render-engine-pg-cms

A lightweight FastAPI CMS for [render-engine](https://github.com/render-engine/render-engine) sites backed by the PostgreSQL collection plugin. Content types, columns, insert, and read SQL are all read from the site's `pyproject.toml` (`[tool.render-engine.pg]`) — adding a new content type to the site makes it available in the CMS automatically.

**What it does on top of basic CRUD:**
- Syndicates posts to [Mastodon](docs/syndication.md) and [Bluesky](docs/syndication.md) from a single modal, with a canonical-URL append toggle.
- Tracks [webmentions](docs/webmentions.md) from bridgy with a live-progress sync log, per-type breakdown (♥ / 🔁 / 💬), and auto-refresh.
- Drag-and-drop [image uploads](docs/uploads.md) to Azure Blob Storage with server-side resize + WebP/JPEG re-encoding.
- [AI slug and tag suggestions](docs/ai.md) from a local Ollama server.
- [Auto-publish](docs/publishing.md) via GitHub Actions on save, with trailing-edge debounce.

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just).

```bash
cd render-engine-pg-cms
cp .env.example .env          # set CONNECTION_STRING at minimum
just install
just dev                      # http://localhost:8000
```

## Documentation

- **[Configuration](docs/configuration.md)** — every env var in one place.
- **[Content types](docs/content-types.md)** — how pyproject.toml drives the CMS.
- **[Publishing](docs/publishing.md)** — manual trigger, auto-publish, debounce rules.
- **[Syndication](docs/syndication.md)** — Mastodon + Bluesky, draft + send, append-URL toggle.
- **[Webmentions](docs/webmentions.md)** — bridgy setup, sync loop, per-record refresh.
- **[Image uploads](docs/uploads.md)** — Azure Blob + Pillow optimization + drag/drop UX.
- **[AI suggestions](docs/ai.md)** — Ollama-backed slug + tag generators.
- **[HTTP API](docs/api.md)** — non-CRUD endpoints for automation.
- **[Database migrations](docs/migrations.md)** — SQL files in `sql/` and how to apply them.
- **[Extension](docs/extension.md)** — the Firefox/Zen quick-capture add-on.

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
