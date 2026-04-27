-- ============================================================================
-- Migration 018: 任务执行历史表 + 管理员审计日志表
-- 目的：将 Celery 任务执行状态持久化，支持前端任务监控和审计追溯
-- 应用于：2026-04-25
-- ============================================================================

-- 任务执行历史表
CREATE TABLE IF NOT EXISTS task_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    celery_task_id VARCHAR(255),             -- Celery 生成的 task ID（可空，支持手动创建的恢复任务）
    task_name VARCHAR(255) NOT NULL,         -- 如 "run_ingest", "run_extraction"
    queue VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
        -- pending / running / retrying / failed / succeeded / cancelled
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 0,
    args JSONB DEFAULT '[]',
    kwargs JSONB DEFAULT '{}',
    error_message TEXT,                      -- 最后一次失败的简要错误消息
    error_traceback TEXT,                    -- 完整堆栈（可选）
    document_id UUID REFERENCES documents(document_id) ON DELETE SET NULL,
    space_id UUID REFERENCES knowledge_spaces(space_id) ON DELETE SET NULL,
    progress_detail JSONB DEFAULT '{}',      -- 可选的进度详情（如当前步骤/已处理数）
    needs_manual_review BOOLEAN DEFAULT FALSE, -- 两次失败后标记为需人工处理
    manual_action_taken VARCHAR(50),         -- retried / cancelled / ignored / reverted
    manual_action_by VARCHAR(255),           -- 操作人标识
    manual_action_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ                 -- 成功或最终失败时间
);

-- 索引：按状态和人工审核标记快速筛选
CREATE INDEX IF NOT EXISTS idx_te_status ON task_executions(status);
CREATE INDEX IF NOT EXISTS idx_te_task_name ON task_executions(task_name);
CREATE INDEX IF NOT EXISTS idx_te_created_at ON task_executions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_te_document_id ON task_executions(document_id);
CREATE INDEX IF NOT EXISTS idx_te_needs_review ON task_executions(needs_manual_review, status);
CREATE INDEX IF NOT EXISTS idx_te_celery_id ON task_executions(celery_task_id);

-- 管理员操作审计日志表
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    operator_name VARCHAR(255),
    action VARCHAR(255) NOT NULL,            -- 如 "retry_task", "cancel_task", "update_config"
    target_type VARCHAR(100),                -- 如 "task", "user", "document", "config"
    target_id VARCHAR(255),
    details JSONB DEFAULT '{}',
    client_ip VARCHAR(45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aal_action ON admin_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_aal_created_at ON admin_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_aal_operator ON admin_audit_log(operator_id);
CREATE INDEX IF NOT EXISTS idx_aal_target ON admin_audit_log(target_type, target_id);
