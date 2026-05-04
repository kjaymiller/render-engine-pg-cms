---
title: "pyproject.toml schema"
description: "The keys under [tool.render-engine.pg] that the CMS reads from the site's pyproject.toml."
---

# pyproject.toml schema

The CMS reads two sections from the render-engine site's `pyproject.toml` (path set by `SITE_PYPROJECT`).

## `[tool.render-engine.pg.insert_sql]`

One key per content type. Value is either a single SQL statement or a list of statements.

```toml
[tool.render-engine.pg.insert_sql]
microblog = "INSERT INTO microblog (slug, content, date) VALUES ({slug}, {content}, {date});"

# Multi-statement form for tag-related joins:
notes = [
  "INSERT INTO notes (slug, title, content, date) VALUES ({slug}, {title}, {content}, {date});",
  "INSERT INTO tags (name) VALUES ({name}) ON CONFLICT DO NOTHING;",
  "INSERT INTO notes_tags (notes_id, tag_id) SELECT (SELECT id FROM notes WHERE slug = {slug}), (SELECT id FROM tags WHERE name = {name});",
]
```

## `[tool.render-engine.pg.read_sql]`

One key per content type. Value is the SELECT used by list views.

```toml
[tool.render-engine.pg.read_sql]
microblog = "SELECT id, slug, content, date FROM microblog ORDER BY date DESC"
```

## Placeholder conversion

Render-engine SQL uses `{slug}` / `{content}` / etc. At load time, `config.py` rewrites those to `%(slug)s` / `%(content)s` so psycopg can bind named parameters. You write the SQL once and both render-engine and the CMS use it directly.

## How statements are classified

For each entry in `insert_sql`, the CMS inspects the statements:

- The statement whose target table matches the content-type name → **primary insert**. Its columns define the edit-form fields.
- A statement targeting `tags` → marks the type as having tags.
- A statement targeting `<ct>_tags` → marks the join.

If no statement targets the content-type name, the first statement is the primary insert.

## What's derived

- **Edit-form fields**: every column in the primary INSERT *except* `id`, `created_at`, `updated_at`.
- **Required-by-convention**: `slug`, `title`, `name`, `content`.
- **List view**: runs `read_sql`.
- **Edit load**: `SELECT * FROM <table> WHERE id = %(id)s`.
- **Update**: `UPDATE <table> SET ... WHERE id = ...` is generated from the primary insert's column set (no explicit update SQL).
- **Tag UI**: shown only when both `tags` and `<ct>_tags` statements exist.

## Field rendering rules

Input type per column name (decided in `templates/edit.html`):

| Column name                 | Input                                       |
| --------------------------- | ------------------------------------------- |
| `content`                   | `<textarea>` + drag/drop image upload       |
| `description`               | Short `<textarea>`                          |
| `date`                      | `datetime-local` + "Now" button             |
| `slug`                      | `<input>` + AI "Suggest" button             |
| `title` / `name`            | `<input>`, auto-slugifies into `slug`       |
| `image_url`                 | `<input type="url">` + drag/drop upload     |
| `external_link`, `url`      | `<input type="url">`                        |
| `latitude`, `longitude`     | `<input type="number">`                     |
| `location`                  | `<input>` + "Look up" geocode (OSM)         |
| anything else               | plain `<input type="text">`                 |

Tags get a comma-separated `<input>` plus AI "Suggest" + chip-toggle UI when supported.

## Timeline membership

Only `microblog`, `blog`, `notes` show on the home timeline. Other types still get `/c/<name>` list/edit pages. Edit `TIMELINE_TYPES` in `main.py` to change.
