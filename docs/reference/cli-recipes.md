---
title: "CLI recipes"
description: "Every `mise` task the CMS ships and what it does."
---

# CLI recipes

| Command                      | What it does                                         |
| ---------------------------- | ---------------------------------------------------- |
| `mise run install`               | `uv sync` — create venv + install deps               |
| `mise run dev [host] [port]`     | Run uvicorn with `--reload`                          |
| `mise run publish`               | Trigger the site's GitHub publish workflow           |
| `mise run sync-webmentions`      | Full webmention sync from the CLI (prints results)   |
| `mise run load-sql sql/<file>`   | Apply an idempotent migration against the DB         |
| `mise run backport-syndication`  | Dry-run backfill of `mastodon_url` / `bluesky_url`   |
| `mise run extension`             | Package the `.xpi` for Zen/Firefox                   |
| `mise run lock`                  | `uv lock --upgrade`                                  |
| `mise run docs`            | Build the static docs site into `docs-site/output/`  |
| `mise run docs-serve`            | Serve the built docs locally                         |

List every task with `mise tasks`. Secrets are injected from fnox (age-encrypted) via `fnox exec`. See [configuration.md](configuration.md#secrets-fnox--age) for the keys and how to set them.
