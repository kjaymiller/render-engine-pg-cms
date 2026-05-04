---
title: "HTTP API"
description: "Every endpoint the CMS exposes, with parameters and response shapes."
---

# HTTP API

The browser-facing routes (form handlers, HTML pages, image upload, AI helpers) are **unauthenticated** — they're meant for localhost or a private network. The programmatic JSON API under `/api/v1/` requires a bearer token (see [JSON API](#json-api-apiv1) below) so it can safely be exposed to other tools and agents.

## CRUD (per content type)

| Method | Path                              | Purpose                    |
| ------ | --------------------------------- | -------------------------- |
| GET    | `/`                               | Unified timeline (home)    |
| GET    | `/c/{name}`                       | List records for a type    |
| GET    | `/c/{name}/new`                   | New-record form            |
| POST   | `/c/{name}/new`                   | Create record              |
| GET    | `/c/{name}/{id}`                  | Edit form                  |
| POST   | `/c/{name}/{id}`                  | Update record              |
| POST   | `/c/{name}/{id}/delete`           | Delete record              |
| GET    | `/quick`                          | Browser-extension entry    |

Form handlers redirect (303) to a list view with a flash. Errors re-render the edit form with per-field errors.

## Syndication

| Method | Path                                | Target                            |
| ------ | ----------------------------------- | --------------------------------- |
| POST   | `/c/{name}/{id}/mastodon`           | Mastodon only                     |
| POST   | `/c/{name}/{id}/bluesky`            | Bluesky only                      |
| POST   | `/c/{name}/{id}/syndicate`          | Both (form-driven checkboxes)     |

## Webmentions

| Method | Path                                       | Purpose                                            |
| ------ | ------------------------------------------ | -------------------------------------------------- |
| GET    | `/webmentions`                             | Log page with live status, breakdown chips, filter |
| POST   | `/webmentions/sync`                        | Start a full sync (manual trigger)                 |
| GET    | `/webmentions/status`                      | JSON status + streaming deltas (`?since=N`)        |
| POST   | `/c/{name}/{id}/webmentions/sync`          | Refresh one record                                 |

### `GET /webmentions/status?since=N`

```json
{
  "running": true,
  "started_at": "2026-04-22T15:30:00Z",
  "finished_at": null,
  "last_update": "2026-04-22T15:30:18Z",
  "trigger": "manual",
  "error": null,
  "total_expected": 87,
  "processed": 12,
  "total": 12,
  "ok": 11,
  "failed": 1,
  "changed": 3,
  "new": [
    {"type": "microblog", "id": 42, "slug": "...", "prev": 0, "count": 2,
     "types": {"like": 2}, "error": null}
  ]
}
```

`since=N` returns only results past index N — drives the live streaming UI.

### `POST /webmentions/sync`

- Form POST: redirects to referrer with a flash.
- JSON POST (`Accept: application/json`): returns `{"ok": true, "started": bool, "running": true}`.

Idempotent — if a sync is already running, `started: false`.

## Image upload

### `POST /api/upload`

Multipart form with a single `file` field.

```json
{
  "url": "https://account.blob.core.windows.net/uploads/photo-a3b9c7d1.webp",
  "filename": "photo.jpg",
  "content_type": "image/webp",
  "original_content_type": "image/jpeg",
  "size": 184210,
  "original_size": 2103840,
  "saved_bytes": 1919630
}
```

Errors:

| Code | Cause                                              |
| ---- | -------------------------------------------------- |
| 400  | Unsupported content type, empty upload, Azure config invalid. |
| 413  | Exceeds `MAX_UPLOAD_BYTES` (50 MiB).               |
| 502  | Unexpected upstream failure.                       |
| 503  | Azure storage not configured.                      |

## AI

### `POST /api/ai/slug`

| Field  | Type | Notes                                  |
| ------ | ---- | -------------------------------------- |
| `text` | form | Required. Title or content to slugify. |

Response: `{"slug": "...", "source": "ai" | "fallback"}`. Always 200 — falls back to rule-based slugify.

### `POST /api/ai/tags`

| Field  | Type | Notes                |
| ------ | ---- | -------------------- |
| `text` | form | Required. Post body. |

Response: `{"suggestions": [{"tag": "...", "known": bool}, ...], "source": "ai"}`.

503 when Ollama is unreachable — no fallback for tags.

## Geocoding

### `GET /api/geocode?q=<query>`

Proxies a single OSM Nominatim search. Used by the `location` field on conferences/events.

Response: `{"display_name": "...", "lat": 0.0, "lon": 0.0}`.

## Publish

### `POST /publish`

Dispatches the configured GitHub Actions workflow. Returns rendered `publish_result.html` with success/error message.

## JSON API (`/api/v1`)

A token-protected REST surface for scripts and agents. All requests require:

```
Authorization: Bearer $CMS_API_TOKEN
```

The token is read from the `CMS_API_TOKEN` environment variable. If the variable is unset on the server, every `/api/v1` request returns 503 — there is no implicit "no auth" mode. Comparison is constant-time (`hmac.compare_digest`).

Errors use standard status codes with `{"detail": "..."}` bodies:

| Code | Cause                                                          |
| ---- | -------------------------------------------------------------- |
| 400  | Malformed payload (bad ISO date, `tags` not a list) or DB error. |
| 401  | Missing or invalid bearer token.                                 |
| 404  | Unknown content type or record id.                               |
| 502  | GitHub workflow dispatch failed.                                 |
| 503  | `CMS_API_TOKEN` not configured.                                  |

### Endpoints

| Method | Path                                  | Purpose                                            |
| ------ | ------------------------------------- | -------------------------------------------------- |
| GET    | `/api/v1/content-types`               | List configured types, columns, tag support       |
| GET    | `/api/v1/c/{name}`                    | List records (`?status=`, `?limit=`, `?offset=`)  |
| GET    | `/api/v1/c/{name}/{id}`               | Fetch one (with `tags` when applicable)           |
| POST   | `/api/v1/c/{name}`                    | Create (201)                                      |
| PATCH  | `/api/v1/c/{name}/{id}`               | Partial update                                    |
| DELETE | `/api/v1/c/{name}/{id}`               | Delete (204)                                      |
| POST   | `/api/v1/c/{name}/{id}/syndicate`     | Post to Mastodon and/or Bluesky                   |
| POST   | `/api/v1/publish`                     | Trigger the GitHub publish workflow               |

### Query parameters on list

| Param    | Default | Notes                                              |
| -------- | ------- | -------------------------------------------------- |
| `status` | `all`   | One of `all`, `published`, `drafts`, `scheduled`. |
| `limit`  | `50`    | 1–500.                                             |
| `offset` | `0`     | For paging; `total` in the response is unfiltered. |

### Create / update payload

JSON body. Keys that match the content type's primary columns are accepted; unknown keys are ignored. Special keys:

- `tags` — list of strings; replaces existing tag set on update.
- `draft` — boolean. Records with `draft: true` are excluded from auto-publish.
- `date` — ISO 8601 string. A future `date` makes the record "scheduled" and skips auto-publish until that time.

```bash
curl -X POST https://cms.example.com/api/v1/c/microblog \
  -H "Authorization: Bearer $CMS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "hello-from-claude",
    "content": "First draft via API.",
    "draft": true,
    "tags": ["meta", "automation"]
  }'
```

Create returns `{"created": <record>}` and fires the same auto-publish debounce as the form handler. For content types without a `slug` column the response echoes the submitted values rather than the persisted row (no `RETURNING id` available against the host site's configured `INSERT`).

### Syndicate

```json
POST /api/v1/c/microblog/42/syndicate
{
  "text": "optional override; defaults to the auto-built status text",
  "mastodon": true,
  "bluesky": true
}
```

Response:

```json
{
  "mastodon": {"url": "https://mastodon.social/@you/123", "id": "123"},
  "bluesky":  {"url": "https://bsky.app/profile/you/post/abc", "uri": "at://..."},
  "errors":   {}
}
```

If a record already has `mastodon_url` / `bluesky_url`, that network's slot returns `{"url": "...", "skipped": true}` and is not re-posted. Per-network failures land in `errors` without aborting the other network.

### Publish

```bash
curl -X POST https://cms.example.com/api/v1/publish \
  -H "Authorization: Bearer $CMS_API_TOKEN"
```

Returns `{"dispatched": true}`. Poll `GET /publish/status` (browser-facing, unauthenticated) for run state.

## Rate limiting

None built in. The webmention auto-loop has its own throttles (age filter, startup stampede avoidance); everything else is hit at whatever cadence you drive. The `/api/v1` surface has no per-token quotas — pair it with a reverse proxy if you need them.
