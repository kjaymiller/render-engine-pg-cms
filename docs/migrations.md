---
title: "Database migrations"
description: "The CMS doesn't own the schema — the render-engine site does. But some CMS features need columns the site's base schema doesn't include, so this repo keeps idempotent migration files in `sql/`."
---

# Database migrations

The CMS doesn't own the schema — the render-engine site does. But some CMS features need columns the site's base schema doesn't include, so this repo keeps idempotent migration files in `sql/`.

All migrations use `ADD COLUMN IF NOT EXISTS` or equivalent — safe to re-run. Apply them against the content database once when you add the corresponding feature.

## Running a migration

```bash
just load-sql sql/<migration>.sql
```

Under the hood this does `psql "$CONNECTION_STRING" -f <file>` with the DSN pulled from 1Password.

## Available migrations

### `sql/mastodon_migration.sql`

Adds `mastodon_url text` to `microblog` and `blog`. Required for [syndication](syndication.md) to persist Mastodon post URLs.

### `sql/bluesky_migration.sql`

Adds `bluesky_url text` to `microblog` and `blog`. Required for Bluesky syndication.

### `sql/webmentions_migration.sql`

Adds `webmentions_count integer DEFAULT 0` and `webmentions_synced_at timestamptz` to `microblog` and `blog`. Required for the [webmention](webmentions.md) sync loop.

### `sql/webmention_types_migration.sql`

Adds `webmentions_types jsonb DEFAULT '{}'::jsonb` to `microblog` and `blog`. Required for the per-type breakdown (likes/reposts/replies) chips.

## Which order?

Apply them in roughly this order when bootstrapping a new install:

```bash
just load-sql sql/mastodon_migration.sql
just load-sql sql/bluesky_migration.sql
just load-sql sql/webmentions_migration.sql
just load-sql sql/webmention_types_migration.sql
```

Because they're `IF NOT EXISTS`-guarded, you can also run them in any order or re-run them when unsure.

## Adding your own

Keep new migrations idempotent and small:

```sql
-- sql/my_feature_migration.sql
ALTER TABLE microblog ADD COLUMN IF NOT EXISTS my_column text;
CREATE INDEX IF NOT EXISTS idx_foo ON microblog (my_column);
```

Then `just load-sql sql/my_feature_migration.sql`.

## Don't forget to update `pyproject.toml`

Adding a column to a table doesn't automatically surface it in the CMS — the render-engine site's `pyproject.toml` drives the field list via its `insert_sql` / `read_sql` entries. After a migration, update those SQL strings on the site side and restart the CMS. See [content-types.md](content-types.md).
