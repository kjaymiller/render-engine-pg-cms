-- Adds a column to store the Bluesky post URL after publishing.
--   just load-sql sql/bluesky_migration.sql

ALTER TABLE microblog ADD COLUMN IF NOT EXISTS bluesky_url text;
ALTER TABLE blog      ADD COLUMN IF NOT EXISTS bluesky_url text;
