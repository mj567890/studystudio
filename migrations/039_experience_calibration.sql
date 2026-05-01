-- Migration 039: Experience calibration (动态访谈)
-- 教师隐性知识抽取：5道选择题 → 结构化JSONB

ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS experience_calibration JSONB;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS calibration_quality_issues JSONB;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS calibration_confidence_score FLOAT;

COMMENT ON COLUMN skill_blueprints.experience_calibration IS '教师经验校准数据：真痛点、真实案例、常见误区、优先级排序、红线';
COMMENT ON COLUMN skill_blueprints.calibration_quality_issues IS '校准题自动质检发现的问题';
COMMENT ON COLUMN skill_blueprints.calibration_confidence_score IS '经验校准信息密度评分（0-1），<0.4 触发保守生成模式';
