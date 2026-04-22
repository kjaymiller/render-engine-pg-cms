-- Cache webmention.io counts alongside each record so the UI doesn't have to
-- fetch on every page load. Run once:
--   just load-sql sql/webmentions_migration.sql

ALTER TABLE microblog ADD COLUMN IF NOT EXISTS webmentions_count integer DEFAULT 0;
ALTER TABLE microblog ADD COLUMN IF NOT EXISTS webmentions_synced_at timestamptz;

ALTER TABLE blog ADD COLUMN IF NOT EXISTS webmentions_count integer DEFAULT 0;
ALTER TABLE blog ADD COLUMN IF NOT EXISTS webmentions_synced_at timestamptz;
