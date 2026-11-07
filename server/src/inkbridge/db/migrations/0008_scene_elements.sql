-- INK-110 (decision 0077): one row per scene element instead of one JSON blob per canvas.
--
-- ONE-WAY STEP. Back up the database first, with the API stopped:
--   sqlite3 data/inkbridge.db ".backup data/inkbridge.pre-0008.db"   (or cp data/inkbridge.db ...)
-- Rolling back means restoring that backup. The old column scenes.elements_json is kept for one
-- release but is no longer written or read after this migration.
-- The rows are filled from the blobs by db.migrations._backfill_scene_rows, in this transaction.
CREATE TABLE scene_elements (
    document_id TEXT NOT NULL REFERENCES documents(id),
    id TEXT NOT NULL,
    pos INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    version INTEGER NOT NULL,
    nonce INTEGER NOT NULL,
    is_deleted INTEGER NOT NULL CHECK (is_deleted IN (0, 1)),
    json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (document_id, id)
);
CREATE INDEX scene_elements_seq ON scene_elements (document_id, seq);
