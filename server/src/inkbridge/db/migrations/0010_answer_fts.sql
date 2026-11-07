-- One row per answered question (INK-136). Vault text is never stored here: sources_json stays in questions.
CREATE VIRTUAL TABLE answer_fts USING fts5(
    question_id UNINDEXED,
    document_id UNINDEXED,
    question,
    answer
);
INSERT INTO answer_fts (question_id, document_id, question, answer)
    SELECT id, document_id, text, answer_md FROM questions
    WHERE status = 'answered' AND answer_md IS NOT NULL;
