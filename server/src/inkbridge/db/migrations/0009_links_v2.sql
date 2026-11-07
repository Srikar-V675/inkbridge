-- INK-122 (decision 0081): links gain source, label, confidence and element_id, and documents gain
-- a per-canvas chunker choice.
--
-- ONE-WAY STEP. Back up the database first, with the API stopped:
--   sqlite3 data/inkbridge.db ".backup data/inkbridge.pre-0009.db"   (or cp data/inkbridge.db ...)
-- Rolling back means restoring that backup. Existing rows become source 'stroke' with no element.
-- element_id is NOT NULL DEFAULT empty so it can sit in the primary key.
CREATE TABLE links_new (
    document_id TEXT NOT NULL REFERENCES documents(id),
    from_region TEXT NOT NULL REFERENCES regions(id),
    to_region   TEXT NOT NULL REFERENCES regions(id),
    kind        TEXT NOT NULL CHECK (kind IN ('arrow', 'near', 'answer', 'relates', 'derived')),
    source      TEXT NOT NULL DEFAULT 'stroke' CHECK (source IN ('stroke', 'agent', 'user')),
    label       TEXT,
    confidence  REAL,
    element_id  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (document_id, from_region, to_region, kind, source, element_id)
);
INSERT INTO links_new (document_id, from_region, to_region, kind)
    SELECT document_id, from_region, to_region, kind FROM links;
DROP TABLE links;
ALTER TABLE links_new RENAME TO links;
ALTER TABLE documents ADD COLUMN chunker TEXT CHECK (chunker IN ('v1', 'v2'));
