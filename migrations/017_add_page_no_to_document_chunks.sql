-- ================================================================
-- 017_add_page_no_to_document_chunks.sql
-- 为 document_chunks 表添加 page_no 列，支持按页码提取 PDF 文本
-- 日期：2026-04-24
-- ================================================================

ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS page_no INTEGER;
