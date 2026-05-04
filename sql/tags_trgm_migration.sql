-- Trigram fuzzy matching on tag names so we can narrow the AI tag prompt to
-- library entries that are textually relevant to the post, instead of dumping
-- the full library into Ollama's context. Run once:
--   just load-sql sql/tags_trgm_migration.sql

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS tags_name_trgm_idx
    ON tags USING gin (name gin_trgm_ops);
