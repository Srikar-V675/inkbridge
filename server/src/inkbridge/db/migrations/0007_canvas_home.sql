ALTER TABLE documents ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1));
ALTER TABLE documents ADD COLUMN archived_at TEXT;
ALTER TABLE documents ADD COLUMN last_opened_at TEXT;
