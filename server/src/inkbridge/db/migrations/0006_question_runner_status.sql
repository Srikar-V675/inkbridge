ALTER TABLE questions ADD COLUMN runner_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (runner_status IN ('pending', 'running', 'failed'));
ALTER TABLE questions ADD COLUMN runner_error TEXT;
