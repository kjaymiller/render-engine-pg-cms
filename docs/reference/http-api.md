---
title: "HTTP API"
description: "Every endpoint the CMS exposes, with parameters and response shapes."
---

# HTTP API

All endpoints are **unauthenticated** — the CMS is meant to run on localhost or behind a private network.

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

## Rate limiting

None built in. The webmention auto-loop has its own throttles (age filter, startup stampede avoidance); everything else is hit at whatever cadence you drive.
