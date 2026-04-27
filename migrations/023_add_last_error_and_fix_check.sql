-- ================================================================
-- 023_add_last_error_and_fix_check.sql
-- 修复：documents 表添加 last_error 列，补充 failed/extracting 状态
-- 背景：system_health.py 和 router.py 中 all-documents 等端点
--       引用 last_error 列但迁移未包含，导致 UndefinedColumnError
-- 日期：2026-04-27
-- ================================================================

-- 1. 添加 last_error 列
ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_error TEXT;

-- 2. 删除旧 CHECK 约束，重建（补充 failed + extracting）
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_document_status_check;

ALTER TABLE documents ADD CONSTRAINT documents_document_status_check
    CHECK (document_status IN (
        'uploaded',
        'parsed',
        'extracting',
        'extracted',
        'embedding',
        'reviewed',
        'published',
        'failed'
    ));
