---
title: "CLI recipes"
description: "Every `just` target the CMS ships and what it does."
---

# CLI recipes

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
| `just docs-build`            | Build the static docs site into `docs-site/output/`  |
| `just docs-serve`            | Serve the built docs locally                         |

Secrets used by these recipes are read from 1Password via `op read`. See [configuration.md](configuration.md#1password-integration) for the secret references and how to swap them out.
