-- migrations/034_course_proposals.sql
-- 阶段 1：课程方案提案 — AI 生成 3 套可选课程设计方案
-- 2026-05-01

BEGIN;

-- ─────────────────────────────────────────────────────────────
-- knowledge_spaces：存储 AI 生成的课程方案
-- ─────────────────────────────────────────────────────────────
ALTER TABLE knowledge_spaces ADD COLUMN IF NOT EXISTS course_proposals jsonb;
ALTER TABLE knowledge_spaces ADD COLUMN IF NOT EXISTS proposals_generated_at timestamptz;

COMMENT ON COLUMN knowledge_spaces.course_proposals IS 'AI 生成的 3-4 套课程设计方案，每套包含目标受众、教学风格、课程结构等';
COMMENT ON COLUMN knowledge_spaces.proposals_generated_at IS '方案生成时间，用于判断是否需要重新生成';

-- ─────────────────────────────────────────────────────────────
-- documents：材料特征摘要（轻量，仅用于 prompt 输入）
-- ─────────────────────────────────────────────────────────────
ALTER TABLE documents ADD COLUMN IF NOT EXISTS material_summary jsonb;

COMMENT ON COLUMN documents.material_summary IS '材料特征摘要：material_type、difficulty_level、knowledge_density 等，聚合自所有 chunk 分析';

-- ─────────────────────────────────────────────────────────────
-- skill_blueprints：教师选中的方案
-- ─────────────────────────────────────────────────────────────
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS selected_proposal jsonb;

COMMENT ON COLUMN skill_blueprints.selected_proposal IS '教师选中的课程方案（完整 JSON）+ 填空修改值';

COMMIT;
