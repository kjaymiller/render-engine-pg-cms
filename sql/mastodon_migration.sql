-- Adds a column to store the Mastodon status URL after publishing a post.
-- Run once against your render-engine content database.
--
--   psql "$CONNECTION_STRING" -f sql/mastodon_migration.sql

ALTER TABLE microblog ADD COLUMN IF NOT EXISTS mastodon_url text;
ALTER TABLE blog      ADD COLUMN IF NOT EXISTS mastodon_url text;
