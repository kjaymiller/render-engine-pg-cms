---
title: "Configuration reference"
description: "Every environment variable the CMS reads, what it does, and its default."
---

# Configuration reference

The CMS reads configuration from environment variables plus the site's `pyproject.toml`. The `mise run dev` task injects secrets from fnox (age-encrypted) on the fly; anything not managed there goes in `.env` and is loaded via `python-dotenv`.

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

## Chat backend (AI slug + description suggestions)

Any server that speaks the OpenAI chat-completions protocol works — vLLM,
MLX (omlx), llama.cpp's server, Ollama, OpenRouter, OpenAI itself.

| Variable                | Purpose                                                                   | Default |
| ------------------------ | -------------------------------------------------------------------------- | ------- |
| `CHAT_BASE_URL`          | Base URL, up to and including `/v1` if the server expects it. `/chat/completions` is appended. | — |
| `CHAT_MODEL`             | Model id exactly as the server reports it via `GET /v1/models`.            | —       |
| `CHAT_API_KEY`           | Optional. Omitted from the request entirely when unset.                    | —       |
| `CHAT_DISABLE_THINKING`  | `"true"` to render the chat template with thinking off, for reasoning models (e.g. Qwen3) that would otherwise spend the response on reasoning content nobody reads. Not part of the OpenAI protocol proper — a server that doesn't understand the field may reject the whole request, so it's opt-in per deployment. | `false` |

## Secrets (fnox + age)

Secrets are stored in `fnox.toml`, encrypted with [age](https://github.com/FiloSottile/age) via [fnox](https://github.com/jdx/fnox). The file is safe to commit — decryption needs the age identity referenced by `key_file` in `fnox.toml` (kept outside the repo, e.g. `~/.config/fnox/age-identity.txt`). The mise tasks inject them at runtime with `fnox exec -- <command>`.

Keys stored in fnox:

```
CONNECTION_STRING
MASTODON_ACCESS_TOKEN
WEBMENTION_IO_TOKEN
BLUESKY_APP_PASSWORD
GITHUB_TOKEN
AZURE_STORAGE_CONNECTION_STRING
CMS_API_TOKEN
CHAT_API_KEY
```

Set or rotate a value (reads from stdin, never touches shell history):

```bash
printf '%s' "<value>" | fnox set CONNECTION_STRING -p age
```

Inspect keys with `fnox ls`. Anything non-secret goes in `.env` and is loaded via `python-dotenv`.
