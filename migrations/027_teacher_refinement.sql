-- 027_teacher_refinement.sql
-- 教师课程迭代三层方案支撑列
-- 日期：2026-04-28

-- Layer 1: 生成前约束 — 教师将自己的教学要求写入蓝图
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS teacher_instruction text;

-- Layer 2: 章节精调版本追踪
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS refined_at timestamptz;
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS refinement_version integer DEFAULT 0;

-- Layer 3: 自动联动开关（蓝图级别，教师可控制）
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS auto_regen_quiz boolean DEFAULT true;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS auto_regen_discussion boolean DEFAULT false;
