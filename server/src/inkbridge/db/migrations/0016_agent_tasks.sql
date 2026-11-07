-- INK-133 (decision 0095): the work queue behind questions and tapped offers.
CREATE TABLE agent_tasks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    kind TEXT NOT NULL CHECK (kind IN ('question','offer','revise','brief')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','done','failed','cancelled')),
    question_id TEXT, offer_id TEXT,
    input_json TEXT NOT NULL DEFAULT '{}',
    claimed_by TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    created_at TEXT NOT NULL, claimed_at TEXT, finished_at TEXT
);
CREATE INDEX agent_tasks_queue ON agent_tasks (document_id, status, created_at);
CREATE UNIQUE INDEX agent_tasks_question ON agent_tasks (question_id) WHERE question_id IS NOT NULL;
CREATE UNIQUE INDEX agent_tasks_offer ON agent_tasks (offer_id) WHERE offer_id IS NOT NULL;
INSERT INTO agent_tasks (id, document_id, kind, status, question_id, input_json, created_at)
  SELECT 't' || id, document_id, 'question', 'pending', id, '{"mode":"question"}', created_at
  FROM questions WHERE status = 'pending';
