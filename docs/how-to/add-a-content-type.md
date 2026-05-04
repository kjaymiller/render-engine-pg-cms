---
title: "Add a new content type"
description: "Surface a new table from your render-engine site as a content type in the CMS."
---

# Add a new content type

The CMS reads content-type definitions from the render-engine site's `pyproject.toml` — there's no schema in this repo. Adding a type means editing the site's config and restarting the CMS.

## Steps

1. **Add the migration to your site's schema.** Whatever defines `microblog`/`blog` for your site — apply the same kind of migration for the new table.

2. **Add `insert_sql` and `read_sql` entries** to the site's `pyproject.toml`:

   ```toml
   [tool.render-engine.pg.insert_sql]
   notes = "INSERT INTO notes (slug, title, content, date) VALUES ({slug}, {title}, {content}, {date});"

   [tool.render-engine.pg.read_sql]
   notes = "SELECT id, slug, title, content, date FROM notes ORDER BY date DESC"
   ```

   For a type with tags, supply a list of statements covering the tag join — see [reference/pyproject-schema.md](../reference/pyproject-schema.md).

3. **Restart the CMS** — `pyproject.toml` is loaded once on first request. Ctrl-C and `just dev` again.

4. **Verify**: the type appears in the masthead nav and at `/c/<name>`. Click **New** to confirm the edit form has the columns you expect.

## What gets derived automatically

- Edit-form fields = every column in the primary INSERT except `id`, `created_at`, `updated_at`.
- Required-by-convention columns: `slug`, `title`, `name`, `content`.
- Tag UI shows when both `tags` and `<ct>_tags` statements are present.
- Field input types are picked by column name — see the [pyproject schema reference](../reference/pyproject-schema.md#field-rendering-rules).

## Showing the type on the home timeline

Only `microblog`, `blog`, and `notes` appear on `/`. Other types (e.g. `conferences`) get list/edit pages but don't clutter the timeline.

To add a type to the timeline, edit `TIMELINE_TYPES` in `src/render_engine_pg_cms/main.py`.
