-- ================================================================
-- 014_fix_document_status_check.sql
-- 修复：将 'embedding' 加入 documents 表的 CHECK 约束
-- 背景：auto_review_tasks 使用 'embedding' 作为文档状态中间态，
--       但原始约束未包含此状态值，导致 UPDATE 失败。
-- 日期：2026-04-24
-- ================================================================

-- 1. 删除旧约束（PostgreSQL 不支持 ALTER CONSTRAINT，需重建）
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_document_status_check;

-- 2. 添加新约束（包含 'embedding' 状态）
ALTER TABLE documents ADD CONSTRAINT documents_document_status_check
    CHECK (document_status IN (
        'uploaded',    -- 文件已上传，等待解析
        'parsed',      -- 文档已解析为文本块
        'extracted',   -- 知识点已提取
        'embedding',   -- 正在向量化
        'reviewed',    -- 已通过 AI 审核
        'published'    -- 已发布可用
    ));
