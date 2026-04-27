---
title: "Content types"
description: "The CMS does not define its own schema. It reads the render-engine site's `pyproject.toml` and exposes whatever content types it finds — add a table to the site and the CMS picks it up automatically."
---

# Content types

The CMS does not define its own schema. It reads the render-engine site's `pyproject.toml` and exposes whatever content types it finds — add a table to the site and the CMS picks it up automatically.

## Where it looks

`SITE_PYPROJECT` (absolute path) points at the site's `pyproject.toml`. Two sections are read:

```toml
[tool.render-engine.pg.insert_sql]
microblog = "INSERT INTO microblog (slug, content, ...) VALUES ({slug}, {content}, ...);"
# Tag-related joins can be additional statements:
# microblog = [
#   "INSERT INTO microblog (slug, content, date) VALUES ({slug}, {content}, {date});",
#   "INSERT INTO tags (name) VALUES ({name}) ON CONFLICT DO NOTHING;",
#   "INSERT INTO microblog_tags (microblog_id, tag_id) SELECT (SELECT id FROM microblog WHERE slug = {slug}), (SELECT id FROM tags WHERE name = {name});",
# ]

[tool.render-engine.pg.read_sql]
microblog = "SELECT ... FROM microblog LEFT JOIN ..."
```

## Placeholder conversion

Render-engine SQL uses `{slug}` / `{content}` / etc. At load time `config.py` rewrites those to `%(slug)s` / `%(content)s` so psycopg can bind named parameters — you keep the same SQL and the CMS uses it directly.

## How content types are classified

For each entry in `insert_sql`, the CMS inspects the statements:

- The statement whose target table matches the content-type name becomes the **primary insert**; its columns define the edit-form fields.
- A statement targeting `tags` marks the type as having tags.
- A statement targeting `<ct>_tags` marks the join.

If none of the statements match the content-type name, the first statement is used as a fallback.

## What the CMS derives from this

- **Edit form fields**: every column in the primary INSERT other than `id`, `created_at`, `updated_at`. Required-by-convention columns like `slug`, `title`, `name`, `content` are marked required.
- **List view**: runs the `read_sql` query.
- **Edit load**: `SELECT * FROM <table> WHERE id = %(id)s`. No explicit update SQL — an `UPDATE ... SET ... WHERE id = ...` is generated from the primary insert's column set.
- **Tag UI**: shown only when both `tags` and `<ct>_tags` statements exist.

## Timeline (home page)

Only the content types `microblog`, `blog`, `notes` appear on the home timeline. Other types (like `conferences`) still get list/edit pages via `/c/<name>` but don't clutter the homepage feed.

## Adding a new type

1. Add the migration SQL to the site's schema.
2. Add `insert_sql` and `read_sql` entries in the site's `pyproject.toml`.
3. Restart the CMS (`pyproject.toml` is read once on first request).
4. The type shows up in the masthead nav and at `/c/<name>`.

## Field rendering rules

Column name → input type is decided in `templates/edit.html`:

| Column name                             | Input                                     |
| --------------------------------------- | ----------------------------------------- |
| `content`                               | `<textarea>` + drag/drop image upload     |
| `description`                           | Short `<textarea>`                        |
| `date`                                  | `datetime-local` + "Now" button           |
| `slug`                                  | `<input>` + AI "Suggest" button           |
| `title` / `name`                        | `<input>`, auto-slugifies into `slug`     |
| `image_url`                             | `<input type="url">` + drag/drop upload   |
| `external_link`, `url`                  | `<input type="url">`                      |
| `latitude`, `longitude`                 | `<input type="number">`                   |
| `location`                              | `<input>` + "Look up" geocode (OSM)       |
| anything else                           | plain `<input type="text">`               |

Tags (when the type supports them) get a comma-separated `<input>` plus an AI "Suggest" button and chip-toggle UI.
