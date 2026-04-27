-- Migration 012: 新增 blueprint failed 状态 + error_message 字段
-- 为 synthesize_blueprint 任务风暴修复提供失败状态记录能力

ALTER TABLE skill_blueprints
  DROP CONSTRAINT skill_blueprints_status_check;

ALTER TABLE skill_blueprints
  ADD CONSTRAINT skill_blueprints_status_check
  CHECK (status IN ('draft','generating','review','published','archived','failed'));

ALTER TABLE skill_blueprints
  ADD COLUMN IF NOT EXISTS error_message TEXT;
