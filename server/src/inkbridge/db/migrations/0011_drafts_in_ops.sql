-- INK-114 (decision 0086): drafts live in the op row, not in the scene.
--
-- ONE-WAY STEP. Back up the database first, with the API stopped:
--   sqlite3 data/inkbridge.db ".backup data/inkbridge.pre-0011.db"   (or cp data/inkbridge.db ...)
-- Rolling back means restoring that backup.
-- Draft elements still in scene_elements, and ops still `applied`, are moved by
-- db.migrations._move_drafts_out_of_scene in this transaction (it needs the scene, not just SQL).
ALTER TABLE agent_ops ADD COLUMN elements_json TEXT;
ALTER TABLE agent_ops ADD COLUMN box_json TEXT;
ALTER TABLE agent_ops ADD COLUMN question_id TEXT;
ALTER TABLE agent_ops ADD COLUMN task_id TEXT;
ALTER TABLE agent_ops ADD COLUMN offer_id TEXT;
ALTER TABLE agent_ops ADD COLUMN revises TEXT;
ALTER TABLE agent_ops ADD COLUMN diagram_id TEXT;
ALTER TABLE agent_ops ADD COLUMN resolved_at TEXT;
CREATE INDEX agent_ops_resolved ON agent_ops (document_id, resolved_at);
