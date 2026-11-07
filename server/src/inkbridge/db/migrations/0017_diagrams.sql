CREATE TABLE diagrams (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    version INTEGER NOT NULL DEFAULT 0,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('mermaid','graph')),
    source TEXT NOT NULL,
    node_map_json TEXT NOT NULL DEFAULT '{}',
    from_chunks_json TEXT NOT NULL DEFAULT '[]',
    current_op TEXT
);
CREATE INDEX diagrams_document ON diagrams (document_id);
