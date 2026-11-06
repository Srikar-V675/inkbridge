ALTER TABLE documents ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1));
ALTER TABLE documents ADD COLUMN archived_at TEXT;
ALTER TABLE documents ADD COLUMN last_opened_at TEXT;
ALTER TABLE scenes ADD COLUMN element_count INTEGER NOT NULL DEFAULT 0;
UPDATE scenes SET element_count = (
    SELECT COUNT(*) FROM json_each(scenes.elements_json) j
    WHERE json_extract(j.value, '$.isDeleted') IS NOT 1
      AND json_extract(j.value, '$.customData.draft') IS NOT 1);
CREATE INDEX regions_document ON regions (document_id, created_by, status);
CREATE INDEX agent_ops_document ON agent_ops (document_id, status);
