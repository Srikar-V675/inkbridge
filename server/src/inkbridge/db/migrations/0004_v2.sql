-- Spec v3 schema: chunks (successor_of, content_hash), reading hash, links, questions, ops.
ALTER TABLE regions ADD COLUMN successor_of TEXT;
ALTER TABLE regions ADD COLUMN content_hash TEXT;

-- Readings are keyed by the position-independent content hash instead of the exact stroke hash.
-- Old rows keep their old key until db._backfill_v2 re-keys the current ones.
CREATE TABLE recognitions_new (
    region_id    TEXT NOT NULL REFERENCES regions(id),
    content_hash TEXT NOT NULL,
    source       TEXT NOT NULL,
    model        TEXT,
    text         TEXT,
    latex        TEXT,
    text_hash    TEXT,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (region_id, content_hash, source)
);
INSERT INTO recognitions_new (region_id, content_hash, source, model, text, latex, created_at)
    SELECT region_id, stroke_hash, source, model, text, latex, created_at FROM recognitions;
DROP TABLE recognitions;
ALTER TABLE recognitions_new RENAME TO recognitions;

CREATE TABLE links (
    document_id TEXT NOT NULL REFERENCES documents(id),
    from_region TEXT NOT NULL REFERENCES regions(id),
    to_region   TEXT NOT NULL REFERENCES regions(id),
    kind        TEXT NOT NULL CHECK (kind IN ('arrow', 'near')),
    PRIMARY KEY (document_id, from_region, to_region, kind)
);

CREATE TABLE questions (
    id                TEXT PRIMARY KEY,
    document_id       TEXT NOT NULL REFERENCES documents(id),
    parent_id         TEXT REFERENCES questions(id),
    text              TEXT NOT NULL,
    focus_element_ids TEXT NOT NULL DEFAULT '[]',
    answer_md         TEXT,
    sources_json      TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'answered', 'cancelled')),
    runner_ref        TEXT,
    created_at        TEXT NOT NULL
);

ALTER TABLE agent_ops ADD COLUMN document_id TEXT REFERENCES documents(id);
ALTER TABLE agent_ops ADD COLUMN created_at TEXT;
ALTER TABLE agent_ops ADD COLUMN result_json TEXT;
ALTER TABLE agent_ops ADD COLUMN error TEXT;
