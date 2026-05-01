-- migrations/035_blueprint_proposal_fields.sql
-- 阶段 2：蓝图提案选择字段 — 教师选择题+填空题的结果存储
-- 2026-05-01

BEGIN;

-- ─────────────────────────────────────────────────────────────
-- skill_blueprints：教师选择与填空
-- ─────────────────────────────────────────────────────────────
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS selected_proposal_id varchar(10);
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS proposal_adjustments jsonb;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS extra_notes text;

COMMENT ON COLUMN skill_blueprints.selected_proposal_id IS '教师选中的方案 ID（A/B/C）';
COMMENT ON COLUMN skill_blueprints.proposal_adjustments IS '教师的填空修改：total_hours, difficulty, theory_ratio 等';
COMMENT ON COLUMN skill_blueprints.extra_notes IS '教师额外要求（选填文本，逃生舱）';

-- ─────────────────────────────────────────────────────────────
-- 索引
-- ─────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_skill_blueprints_selected_proposal
    ON skill_blueprints (selected_proposal_id)
    WHERE selected_proposal_id IS NOT NULL;

COMMIT;
