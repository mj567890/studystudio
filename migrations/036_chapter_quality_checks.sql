-- migrations/036_chapter_quality_checks.sql
-- 阶段 3：章节质量 — 教学模板追踪 + 自动化质量检查
-- 2026-05-01

BEGIN;

-- ─────────────────────────────────────────────────────────────
-- skill_chapters：教学模板追踪 + 自动化检查结果
-- ─────────────────────────────────────────────────────────────
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS teaching_template_used varchar(30);
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS auto_check_issues jsonb;
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS auto_check_passed boolean DEFAULT false;

COMMENT ON COLUMN skill_chapters.teaching_template_used IS '使用的教学模板：concept_construction / skill_acquisition / problem_solving';
COMMENT ON COLUMN skill_chapters.auto_check_issues IS '自动化质量检查发现的问题列表 [{"type":"...","detail":"..."}]';
COMMENT ON COLUMN skill_chapters.auto_check_passed IS '是否通过所有自动化检查';

-- ─────────────────────────────────────────────────────────────
-- 索引
-- ─────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_skill_chapters_template
    ON skill_chapters (teaching_template_used)
    WHERE teaching_template_used IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_skill_chapters_auto_check
    ON skill_chapters (auto_check_passed, teaching_template_used)
    WHERE auto_check_passed = false;

COMMIT;
