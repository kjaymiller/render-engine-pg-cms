---
title: "Apply a database migration"
description: "Run a SQL migration from `sql/` against the content database, or write a new one."
---

# Apply a database migration

The CMS doesn't own the schema — the render-engine site does — but a few features need columns the site's base schema doesn't include. Those live in `sql/` as idempotent migrations.

## Run an existing migration

```bash
just load-sql sql/<file>.sql
```

Under the hood: `psql "$CONNECTION_STRING" -f <file>`, with the DSN pulled from 1Password.

For the list of migrations and what each adds, see [reference/database-schema.md](../reference/database-schema.md).

## Bootstrap order for a new install

```bash
just load-sql sql/mastodon_migration.sql
just load-sql sql/bluesky_migration.sql
just load-sql sql/webmentions_migration.sql
just load-sql sql/webmention_types_migration.sql
```

All migrations are `IF NOT EXISTS`-guarded — safe to re-run in any order.

## Write your own

Keep migrations small and idempotent:

```sql
-- sql/my_feature_migration.sql
ALTER TABLE microblog ADD COLUMN IF NOT EXISTS my_column text;
CREATE INDEX IF NOT EXISTS idx_foo ON microblog (my_column);
```

Then:

```bash
just load-sql sql/my_feature_migration.sql
```

## Don't forget pyproject.toml

Adding a column doesn't surface it in the CMS automatically. The render-engine site's `pyproject.toml` drives the field list — update its `insert_sql` / `read_sql` strings on the site side and restart the CMS. See [add-a-content-type.md](add-a-content-type.md).
