# render-engine-pg-cms

A lightweight FastAPI CMS for [render-engine](https://github.com/render-engine/render-engine) sites that use the PostgreSQL collection plugin. Content types, columns, insert, and read SQL are all read from the site's `pyproject.toml` (`[tool.render-engine.pg]`), so adding a new content type to the site makes it available in the CMS automatically.

## Features

- Lists / creates / edits / deletes records for every content type defined in `[tool.render-engine.pg.insert_sql]`.
- Uses the site's own `read_sql` for list views and a simple `SELECT * FROM <table>` for edit loads.
- Handles the typical `<content>_tags` / `tags` join pattern when present.
- One-click **Publish** that triggers the site's GitHub Actions `workflow_dispatch`.

## Setup

Requires [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just).

```bash
cd ../render-engine-pg-cms
cp .env.example .env   # set CONNECTION_STRING, SITE_PYPROJECT, GITHUB_*
just install
just dev
```

Open <http://localhost:8000>.

### Common tasks

| Command         | What it does                                    |
| --------------- | ----------------------------------------------- |
| `just install`  | `uv sync` — create venv + install deps          |
| `just dev`      | Run uvicorn with `--reload`                     |
| `just serve`    | Run uvicorn bound to `0.0.0.0:8000`             |
| `just publish`  | Trigger the site's GitHub publish workflow      |
| `just lock`     | `uv lock --upgrade`                             |

## Environment

| Variable          | Purpose                                                                 |
| ----------------- | ----------------------------------------------------------------------- |
| `CONNECTION_STRING` | PostgreSQL DSN — same one the render-engine site uses.                |
| `SITE_PYPROJECT`    | Absolute path to the site's `pyproject.toml`.                         |
| `GITHUB_TOKEN`      | PAT (fine-grained) with `actions:write` on the site repo.             |
| `GITHUB_REPO`       | `owner/repo` — e.g. `kjaymiller/kjaymiller.com`.                      |
| `GITHUB_WORKFLOW`   | Workflow filename. Default: `publish.yml`.                            |
| `GITHUB_REF`        | Branch to dispatch against. Default: `main`.                          |

## How placeholders map to psycopg

The site's SQL uses `{slug}` / `{content}` / etc. At load time those get rewritten to `%(slug)s` / `%(content)s` so psycopg can bind named parameters.

## Caveats

- No auth — run it locally or behind a private network.
- Updates go through a generated `UPDATE <table> SET ... WHERE id = ...` derived from the primary INSERT's columns, since `pyproject.toml` doesn't carry explicit update SQL.
- Requires Starlette ≥ 1.0, which changed `TemplateResponse`'s signature to take `request` as the first positional argument (`TemplateResponse(request, name, context)`). `request` no longer needs to be in the context dict.
