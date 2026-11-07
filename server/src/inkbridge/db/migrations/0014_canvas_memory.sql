-- INK-135 (decision 0093): what an agent should know about a canvas, and how far it has read.
CREATE TABLE canvas_memory (
    document_id   TEXT PRIMARY KEY REFERENCES documents(id),
    brief_md      TEXT NOT NULL DEFAULT '',
    last_seen_seq INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL
);
