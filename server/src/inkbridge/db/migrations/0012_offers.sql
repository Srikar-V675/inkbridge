-- Offers beside the ink (INK-130). The rows double as the feedback log, so nothing is deleted.
CREATE TABLE offers (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    kind TEXT NOT NULL,
    anchor_chunk TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    score REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'triage',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','tapped','dismissed','expired','done')),
    task_id TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX offers_document ON offers (document_id, status);
ALTER TABLE documents ADD COLUMN focus INTEGER NOT NULL DEFAULT 0 CHECK (focus IN (0, 1));
