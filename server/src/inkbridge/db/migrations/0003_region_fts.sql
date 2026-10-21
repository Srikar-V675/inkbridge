-- One row per region: the best-precedence reading of its current ink (see db.save_recognition).
CREATE VIRTUAL TABLE region_fts USING fts5(
    region_id UNINDEXED,
    document_id UNINDEXED,
    text,
    latex
);
