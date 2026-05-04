---
title: "Use the JSON API"
description: "Drive the CMS programmatically — create drafts, update records, syndicate, and publish from a script or agent."
---

# Use the JSON API

The `/api/v1/` surface lets external tools (shell scripts, AI agents, browser extensions running off-host) drive the CMS without scraping HTML form responses. It mirrors the form handlers but returns JSON and requires a bearer token.

## 1. Generate a token

```bash
openssl rand -hex 32
```

Add it to your `.env` (or 1Password/secret manager):

```
CMS_API_TOKEN=<the value you just generated>
```

Restart the server. Without `CMS_API_TOKEN` set, every `/api/v1` request returns 503 — that's deliberate so a misconfigured deploy can't accidentally accept any token.

## 2. Smoke test

```bash
export CMS=https://cms.example.com
export TOKEN=$(grep CMS_API_TOKEN .env | cut -d= -f2)

curl -s "$CMS/api/v1/content-types" -H "Authorization: Bearer $TOKEN" | jq
```

You should see a list of configured types. A 401 means the token is wrong; 503 means the server has no token configured.

## 3. Create a draft

```bash
curl -X POST "$CMS/api/v1/c/microblog" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "hello-from-script",
    "content": "Draft created via API.",
    "draft": true,
    "tags": ["automation"]
  }'
```

Drafts are excluded from auto-publish, so you can stage content without dispatching the GitHub workflow.

## 4. Promote draft → published

```bash
curl -X PATCH "$CMS/api/v1/c/microblog/42" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"draft": false}'
```

The PATCH triggers the same trailing-edge auto-publish debounce the web UI uses. If you save several records back-to-back, they collapse into a single workflow dispatch ~60s after the last save.

## 5. Schedule a post

Set `date` to a future ISO timestamp. The record stays out of auto-publish until that time arrives.

```bash
curl -X POST "$CMS/api/v1/c/blog" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "release-notes",
    "title": "Release Notes",
    "content": "...",
    "date": "2026-06-01T09:00:00+00:00"
  }'
```

## 6. Syndicate

```bash
curl -X POST "$CMS/api/v1/c/microblog/42/syndicate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mastodon": true, "bluesky": true}'
```

Omit `text` to use the auto-built status text (same as the unified "Publish to social" modal). Already-syndicated records return `{"skipped": true}` for that network — re-posting requires clearing the relevant `*_url` column first.

## 7. Trigger a publish manually

```bash
curl -X POST "$CMS/api/v1/publish" -H "Authorization: Bearer $TOKEN"
```

Most callers don't need this — auto-publish handles it on save. Use it when you've made out-of-band DB changes (e.g. a bulk import) and want the static site rebuilt.

## Letting an AI agent drive it

The API is designed so a coding agent (Claude Code, etc.) can manage drafts on your behalf. Two practical guardrails:

1. **Hand the agent a token scoped to a separate `.env`** so you can rotate it independently. Tokens aren't per-user — rotating the env var invalidates whichever copy is in the wild.
2. **Default to `draft: true`** in any prompt template. Reviewing a draft in the editor before flipping it published keeps the agent from publishing typos straight to your feed.

See [HTTP API reference](../reference/http-api.md#json-api-apiv1) for the full endpoint list and response shapes.
