CREATE TABLE documents (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE scenes (
    document_id   TEXT PRIMARY KEY REFERENCES documents(id),
    version       INTEGER NOT NULL DEFAULT 0,
    elements_json TEXT NOT NULL DEFAULT '[]',
    updated_at    TEXT NOT NULL
);

CREATE TABLE regions (
    id               TEXT PRIMARY KEY,
    document_id      TEXT NOT NULL REFERENCES documents(id),
    element_ids_json TEXT NOT NULL DEFAULT '[]',
    bbox             TEXT,
    kind             TEXT,
    created_by       TEXT,
    stroke_hash      TEXT,
    png_path         TEXT,
    status           TEXT NOT NULL DEFAULT 'active',
    updated_at       TEXT
);

CREATE TABLE recognitions (
    region_id   TEXT NOT NULL REFERENCES regions(id),
    stroke_hash TEXT NOT NULL,
    source      TEXT NOT NULL,
    model       TEXT,
    text        TEXT,
    latex       TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (region_id, stroke_hash, source)
);

CREATE TABLE agent_ops (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
);
