-- migrations/009_fork_space.sql
-- Phase 3 Fork: knowledge_spaces 加 fork_from_space_id 字段
-- 记录 fork 来源，为将来版本同步打基础

BEGIN;

ALTER TABLE knowledge_spaces
    ADD COLUMN IF NOT EXISTS fork_from_space_id uuid
        REFERENCES knowledge_spaces(space_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ks_fork_from
    ON knowledge_spaces(fork_from_space_id)
    WHERE fork_from_space_id IS NOT NULL;

COMMENT ON COLUMN knowledge_spaces.fork_from_space_id
    IS 'Fork 来源空间 ID。NULL 表示原创空间；非 NULL 表示从该空间 fork 而来。';

-- fork_tasks: 追踪异步 fork 任务状态
CREATE TABLE IF NOT EXISTS fork_tasks (
    task_id        uuid        PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_space_id uuid       NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    target_space_id uuid       REFERENCES knowledge_spaces(space_id) ON DELETE SET NULL,
    requested_by   uuid        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    status         varchar(20) NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','running','done','failed')),
    error_msg      text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fork_tasks_requester
    ON fork_tasks(requested_by, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fork_tasks_source
    ON fork_tasks(source_space_id);

COMMENT ON TABLE fork_tasks IS 'Fork 异步任务状态追踪表。';

COMMIT;
