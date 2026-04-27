---
title: "Configuration"
description: "Everything the CMS needs is read from environment variables plus the site's `pyproject.toml`. The `just dev` recipe pulls several secrets from 1Password on the fly; anything not managed there goes in `.env` and is loaded via `python-dotenv`."
---

# Configuration

Everything the CMS needs is read from environment variables plus the site's `pyproject.toml`. The `just dev` recipe pulls several secrets from 1Password on the fly; anything not managed there goes in `.env` and is loaded via `python-dotenv`.

## Required

| Variable            | Purpose                                                              |
| ------------------- | -------------------------------------------------------------------- |
| `CONNECTION_STRING` | PostgreSQL DSN — same one the render-engine site uses.               |
| `SITE_PYPROJECT`    | Absolute path to the site's `pyproject.toml`. Defaults to `./pyproject.toml`. |

## GitHub (for the Publish button and auto-publish)

| Variable           | Purpose                                                  | Default       |
| ------------------ | -------------------------------------------------------- | ------------- |
| `GITHUB_TOKEN`     | Fine-grained PAT with `actions:write` on the site repo.  | —             |
| `GITHUB_REPO`      | `owner/repo` (e.g. `kjaymiller/kjaymiller.com`).         | —             |
| `GITHUB_WORKFLOW`  | Workflow filename.                                       | `publish.yml` |
| `GITHUB_REF`       | Branch to dispatch against.                              | `main`        |

## Auto-publish

See [publishing.md](publishing.md).

| Variable                         | Purpose                                                 | Default |
| -------------------------------- | ------------------------------------------------------- | ------- |
| `AUTOPUBLISH`                    | `0`/`false`/`no` to disable auto-publish on save.       | `1`     |
| `AUTOPUBLISH_DEBOUNCE_SECONDS`   | Trailing-edge debounce window in seconds.               | `60`    |

## Mastodon

| Variable                    | Purpose                                         | Default  |
| --------------------------- | ----------------------------------------------- | -------- |
| `MASTODON_INSTANCE`         | Full URL (e.g. `https://mastodon.social`).      | —        |
| `MASTODON_ACCESS_TOKEN`     | User-scoped API token with `write:statuses`.    | —        |
| `MASTODON_VISIBILITY`       | `public` / `unlisted` / `private` / `direct`.   | `public` |

## Bluesky

| Variable                | Purpose                                              |
| ----------------------- | ---------------------------------------------------- |
| `BLUESKY_HANDLE`        | Your handle (e.g. `kjaymiller.com`).                 |
| `BLUESKY_APP_PASSWORD`  | App password (Settings → App Passwords in Bluesky).  |
| `BLUESKY_PDS`           | PDS URL. Default `https://bsky.social`.              |
| `SITE_BASE_URL`         | Used to resolve relative `image_url` values.         |

## Webmentions (webmention.io + bridgy)

See [webmentions.md](webmentions.md).

| Variable                         | Purpose                                                          | Default                       |
| -------------------------------- | ---------------------------------------------------------------- | ----------------------------- |
| `WEBMENTION_IO_TOKEN`            | webmention.io API token (enables auto-loop and richer data).     | —                             |
| `WEBMENTION_URL_TEMPLATE`        | Template for canonical post URL — placeholders `{base}/{type}/{slug}`. | `{base}/{type}/{slug}.html` |
| `WEBMENTION_SYNC_INTERVAL`       | Auto-sync period in seconds. `0` disables the background loop.   | `21600` (6h)                  |
| `WEBMENTION_AUTO_MAX_AGE_DAYS`   | Auto-loop only touches posts whose `date` is within N days. `0` disables the filter. | `60` |

## Azure Blob Storage (image uploads)

See [uploads.md](uploads.md).

| Variable                            | Purpose                                                             |
| ----------------------------------- | ------------------------------------------------------------------- |
| `AZURE_STORAGE_CONNECTION_STRING`   | Full connection string (preferred; bundles account + key + endpoint).|
| `AZURE_STORAGE_ACCOUNT`             | Alternative — account name.                                         |
| `AZURE_STORAGE_KEY`                 | Alternative — account key.                                          |
| `AZURE_STORAGE_CONTAINER`           | Container name (required). Blobs land at the container root.        |
| `AZURE_PUBLIC_BASE_URL`             | Optional CDN/custom-domain prefix. Falls back to default blob URL.  |

## Ollama (AI slug + tag suggestions)

See [ai.md](ai.md).

| Variable         | Purpose                                   | Default                  |
| ---------------- | ----------------------------------------- | ------------------------ |
| `OLLAMA_URL`     | Ollama HTTP endpoint.                     | `http://localhost:11434` |
| `OLLAMA_MODEL`   | Model tag (must be pulled via `ollama pull`). | `llama3.2:3b`        |

## 1Password integration

The `justfile` reads these secret references via `op read` at startup — if you use a different password manager or plain `.env`, adjust the recipes accordingly:

```
db_secret         op://Private/personal-blog/credential
mastodon_secret   op://Private/mastodon.social/access-token
webmention_secret op://Private/Webmention.io/credential
bluesky_secret    op://Private/bluesky/app password
github_secret     op://Private/GH-PAT - Kjaymiller.com PG CMS/credential
azure_secret      op://Private/Azure Storage Connection String/credential
```
