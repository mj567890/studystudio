-- =============================================================================
-- 迁移 025：文档共享引用表
-- 说明：Fork 课程时不再复制文档，而是通过此表授权访问源空间文档
--       解决存储爆炸问题，同时保持溯源功能完整
-- 创建时间：2026-04-28
-- =============================================================================

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════
-- 1. 文档共享引用表
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS space_document_access (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    space_id        UUID NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    document_id     UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_space_id UUID REFERENCES knowledge_spaces(space_id) ON DELETE SET NULL,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 每个空间对同一文档只有一条授权记录
    CONSTRAINT uq_sda_space_document UNIQUE (space_id, document_id)
);

COMMENT ON TABLE space_document_access IS '文档共享引用表：记录哪些空间被授权访问源空间的文档';
COMMENT ON COLUMN space_document_access.space_id IS '被授权空间（fork 方）';
COMMENT ON COLUMN space_document_access.document_id IS '被授权访问的文档';
COMMENT ON COLUMN space_document_access.source_space_id IS '文档实际所属的源空间（用于链式 fork 溯源）';
COMMENT ON COLUMN space_document_access.granted_at IS '授权时间';

-- ═══════════════════════════════════════════════════════════════════════
-- 2. 索引
-- ═══════════════════════════════════════════════════════════════════════

-- 快速查询某空间被授权访问的所有文档
CREATE INDEX IF NOT EXISTS idx_sda_space
    ON space_document_access(space_id);

-- 快速查询某文档被哪些空间引用（用于删除检查）
CREATE INDEX IF NOT EXISTS idx_sda_document
    ON space_document_access(document_id);

-- 快速查询某源空间的文档被多少空间引用（用于删除判断）
CREATE INDEX IF NOT EXISTS idx_sda_source_space
    ON space_document_access(source_space_id)
    WHERE source_space_id IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════
-- 3. 回滚说明
-- ═══════════════════════════════════════════════════════════════════════
-- 回滚脚本（如需）：
--   DROP TABLE IF EXISTS space_document_access;

COMMIT;
