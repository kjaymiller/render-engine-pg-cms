---
title: "Database schema and migrations"
description: "Columns the CMS adds on top of the render-engine site's base schema."
---

# Database schema and migrations

The CMS doesn't own the schema — the render-engine site does. But several CMS features need columns the site's base schema doesn't include. Those live in `sql/` as idempotent (`ADD COLUMN IF NOT EXISTS`) migrations.

To apply, see [the how-to](../how-to/apply-a-migration.md).

## Migration files

### `sql/mastodon_migration.sql`

Adds `mastodon_url text` to `microblog` and `blog`. Required for [Mastodon syndication](../how-to/syndicate-to-mastodon.md) to persist the returned URL.

### `sql/bluesky_migration.sql`

Adds `bluesky_url text` to `microblog` and `blog`. Required for [Bluesky syndication](../how-to/syndicate-to-bluesky.md).

### `sql/webmentions_migration.sql`

Adds to both `microblog` and `blog`:

| Column                  | Type           | Meaning                                       |
| ----------------------- | -------------- | --------------------------------------------- |
| `webmentions_count`     | `integer`      | Total mentions (all types combined).          |
| `webmentions_synced_at` | `timestamptz`  | When the row was last refreshed.              |

### `sql/webmention_types_migration.sql`

Adds `webmentions_types jsonb DEFAULT '{}'::jsonb` to `microblog` and `blog`. Stores the per-type breakdown, e.g. `{"like":3,"repost":1}`.

### Other files

`sql/draft_schedule_migration.sql` and `sql/tags_trgm_migration.sql` are present but currently experimental. Inspect before applying.

## Bootstrap order

```bash
just load-sql sql/mastodon_migration.sql
just load-sql sql/bluesky_migration.sql
just load-sql sql/webmentions_migration.sql
just load-sql sql/webmention_types_migration.sql
```

All idempotent — safe to re-run.
