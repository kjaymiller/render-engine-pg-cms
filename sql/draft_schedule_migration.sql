-- Adds an explicit `draft` flag to time-ordered content types.
-- Scheduling reuses the existing `date` column: a row is "scheduled" when
-- it is not a draft and its `date` is in the future.

ALTER TABLE microblog ADD COLUMN IF NOT EXISTS draft BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE notes     ADD COLUMN IF NOT EXISTS draft BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE blog      ADD COLUMN IF NOT EXISTS draft BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_microblog_draft ON microblog (draft) WHERE draft;
CREATE INDEX IF NOT EXISTS idx_notes_draft     ON notes     (draft) WHERE draft;
CREATE INDEX IF NOT EXISTS idx_blog_draft      ON blog      (draft) WHERE draft;
