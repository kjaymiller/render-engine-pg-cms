-- Store the per-type breakdown from webmention.io so the UI can show
-- likes / reposts / replies separately. Shape matches webmention.io's
-- /api/count `type` field, e.g. {"like": 3, "repost": 1, "in-reply-to": 1}.
-- Run once:
--   just load-sql sql/webmention_types_migration.sql

ALTER TABLE microblog ADD COLUMN IF NOT EXISTS webmentions_types jsonb DEFAULT '{}'::jsonb;
ALTER TABLE blog      ADD COLUMN IF NOT EXISTS webmentions_types jsonb DEFAULT '{}'::jsonb;
