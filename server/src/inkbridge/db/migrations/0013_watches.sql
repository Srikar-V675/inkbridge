-- Chunk reading hashes a vault note was written from (INK-132). Hashes only: no note text, no path.
CREATE TABLE watches (
    document_id TEXT NOT NULL REFERENCES documents(id),
    note_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    reading_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, note_id, chunk_id)
);
