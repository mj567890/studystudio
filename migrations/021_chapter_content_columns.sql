-- 021_chapter_content_columns.sql
-- Phase 8：章节内容字段拆分（结构化存储）
-- 从 content_text JSON blob 中拆分出独立列，API 直接返回字段
-- 全部 NULLABLE，兼容现有数据（旧数据仍通过 content_text JSON fallback）

ALTER TABLE skill_chapters
    ADD COLUMN scene_hook          TEXT,
    ADD COLUMN code_example        TEXT,
    ADD COLUMN misconception_block TEXT,
    ADD COLUMN skim_summary        TEXT,
    ADD COLUMN prereq_adaptive     TEXT;

COMMENT ON COLUMN skill_chapters.scene_hook          IS '场景引入（课程开头吸引注意力的场景）';
COMMENT ON COLUMN skill_chapters.code_example        IS '代码示例（已格式化为 <pre><code> HTML）';
COMMENT ON COLUMN skill_chapters.misconception_block IS '常见误区（常见误解及纠正）';
COMMENT ON COLUMN skill_chapters.skim_summary        IS '速览摘要（快速预览的要点总结）';
COMMENT ON COLUMN skill_chapters.prereq_adaptive     IS '自适应内容（前置知识不足时的简化版内容 JSON）';
