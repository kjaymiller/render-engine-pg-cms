---
title: "Configuration reference"
description: "Every environment variable the CMS reads, what it does, and its default."
---

# Configuration reference

The CMS reads configuration from environment variables plus the site's `pyproject.toml`. The `just dev` recipe pulls several secrets from 1Password on the fly; anything not managed there goes in `.env` and is loaded via `python-dotenv`.

## Required

| Variable            | Purpose                                                               | Default                |
| ------------------- | --------------------------------------------------------------------- | ---------------------- |
| `CONNECTION_STRING` | PostgreSQL DSN — same one the render-engine site uses.                | —                      |
| `SITE_PYPROJECT`    | Absolute path to the site's `pyproject.toml`.                         | `./pyproject.toml`     |

## JSON API auth

| Variable        | Purpose                                                                                                       | Default |
| --------------- | ------------------------------------------------------------------------------------------------------------- | ------- |
| `CMS_API_TOKEN` | Bearer token required by `/api/v1/*`. Unset = the JSON API returns 503 on every call. Generate with `openssl rand -hex 32`. | —       |

## GitHub (Publish button + auto-publish)

| Variable                       | Purpose                                                  | Default       |
| ------------------------------ | -------------------------------------------------------- | ------------- |
| `GITHUB_TOKEN`                 | Fine-grained PAT with `actions:write` on the site repo.  | —             |
| `GITHUB_REPO`                  | `owner/repo`.                                            | —             |
| `GITHUB_WORKFLOW`              | Workflow filename.                                       | `publish.yml` |
| `GITHUB_REF`                   | Branch to dispatch against.                              | `main`        |
| `AUTOPUBLISH`                  | `0`/`false`/`no` to disable auto-publish on save.        | `1`           |
| `AUTOPUBLISH_DEBOUNCE_SECONDS` | Trailing-edge debounce window.                           | `60`          |

## Mastodon

| Variable                | Purpose                                         | Default  |
| ----------------------- | ----------------------------------------------- | -------- |
| `MASTODON_INSTANCE`     | Full URL (e.g. `https://mastodon.social`).      | —        |
| `MASTODON_ACCESS_TOKEN` | User-scoped API token with `write:statuses`.    | —        |
| `MASTODON_VISIBILITY`   | `public` / `unlisted` / `private` / `direct`.   | `public` |

## Bluesky

| Variable               | Purpose                                              | Default              |
| ---------------------- | ---------------------------------------------------- | -------------------- |
| `BLUESKY_HANDLE`       | Your handle (e.g. `kjaymiller.com`).                 | —                    |
| `BLUESKY_APP_PASSWORD` | App password from Bluesky → Settings → App Passwords.| —                    |
| `BLUESKY_PDS`          | PDS URL.                                             | `https://bsky.social`|
| `SITE_BASE_URL`        | Used to resolve relative `image_url` values.         | —                    |

## Webmentions (webmention.io + bridgy)

| Variable                       | Purpose                                                                              | Default                      |
| ------------------------------ | ------------------------------------------------------------------------------------ | ---------------------------- |
| `WEBMENTION_IO_TOKEN`          | webmention.io API token (enables auto-loop and richer data).                         | —                            |
| `WEBMENTION_URL_TEMPLATE`      | Template for canonical post URL — placeholders `{base}/{type}/{slug}`.               | `{base}/{type}/{slug}.html`  |
| `WEBMENTION_SYNC_INTERVAL`     | Auto-sync period in seconds. `0` disables the background loop.                       | `21600` (6h)                 |
| `WEBMENTION_AUTO_MAX_AGE_DAYS` | Auto-loop only touches posts whose `date` is within N days. `0` disables the filter. | `60`                         |

## Azure Blob Storage (image uploads)

| Variable                          | Purpose                                                              | Default |
| --------------------------------- | -------------------------------------------------------------------- | ------- |
| `AZURE_STORAGE_CONNECTION_STRING` | Full connection string (preferred).                                  | —       |
| `AZURE_STORAGE_ACCOUNT`           | Alternative — account name.                                          | —       |
| `AZURE_STORAGE_KEY`               | Alternative — account key.                                           | —       |
| `AZURE_STORAGE_CONTAINER`         | Container name (required). Blobs land at the container root.         | —       |
| `AZURE_PUBLIC_BASE_URL`           | Optional CDN/custom-domain prefix.                                   | —       |

## Ollama (AI slug + tag suggestions)

| Variable       | Purpose                                       | Default                  |
| -------------- | --------------------------------------------- | ------------------------ |
| `OLLAMA_URL`   | Ollama HTTP endpoint.                         | `http://localhost:11434` |
| `OLLAMA_MODEL` | Model tag (must be pulled via `ollama pull`). | `llama3.2:3b`            |

## 1Password integration

The `justfile` reads these secret references via `op read` at startup. If you use a different password manager or plain `.env`, adjust the recipes accordingly.

```
db_secret         op://Private/personal-blog/credential
mastodon_secret   op://Private/mastodon.social/access-token
webmention_secret op://Private/Webmention.io/credential
bluesky_secret    op://Private/bluesky/app password
github_secret     op://Private/GH-PAT - Kjaymiller.com PG CMS/credential
azure_secret      op://Private/Azure Storage Connection String/credential
```
