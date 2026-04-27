-- =============================================================================
-- 迁移 024：空间软删除 + 文档软删除 + 公开分级
-- 说明：为回收站功能和公开课程分级提供数据基础
-- 创建时间：2026-04-28
-- =============================================================================

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════
-- 1. knowledge_spaces 表变更
-- ═══════════════════════════════════════════════════════════════════════

-- 1a. 软删除字段
ALTER TABLE knowledge_spaces
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(user_id);

COMMENT ON COLUMN knowledge_spaces.deleted_at IS '软删除时间戳。NULL=正常，非NULL=在回收站中';
COMMENT ON COLUMN knowledge_spaces.deleted_by IS '删除操作执行者';

-- 1b. 公开分级——独立的允许 Fork 开关
ALTER TABLE knowledge_spaces
    ADD COLUMN IF NOT EXISTS allow_fork BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN knowledge_spaces.allow_fork IS '是否允许他人 Fork。仅当 visibility=public 时生效';

-- 1c. 索引
CREATE INDEX IF NOT EXISTS idx_knowledge_spaces_deleted_at
    ON knowledge_spaces(deleted_at)
    WHERE deleted_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_spaces_public_fork
    ON knowledge_spaces(visibility, allow_fork)
    WHERE visibility = 'public' AND allow_fork = TRUE;

-- ═══════════════════════════════════════════════════════════════════════
-- 2. documents 表变更——文档级软删除
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(user_id);

COMMENT ON COLUMN documents.deleted_at IS '软删除时间戳。NULL=正常，非NULL=已删除但可能被fork空间引用';
COMMENT ON COLUMN documents.deleted_by IS '删除操作执行者';

CREATE INDEX IF NOT EXISTS idx_documents_deleted_at
    ON documents(deleted_at)
    WHERE deleted_at IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════
-- 3. 回滚说明
-- ═══════════════════════════════════════════════════════════════════════
-- 回滚脚本（如需）：
--   DROP INDEX IF EXISTS idx_documents_deleted_at;
--   ALTER TABLE documents DROP COLUMN IF EXISTS deleted_by, DROP COLUMN IF EXISTS deleted_at;
--   DROP INDEX IF EXISTS idx_knowledge_spaces_public_fork;
--   DROP INDEX IF EXISTS idx_knowledge_spaces_deleted_at;
--   ALTER TABLE knowledge_spaces DROP COLUMN IF EXISTS allow_fork, DROP COLUMN IF EXISTS deleted_by, DROP COLUMN IF EXISTS deleted_at;

COMMIT;
