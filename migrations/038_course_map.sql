-- Migration 038: Course Map + calibration routing
-- 在方案选择和内容生成之间插入课程地图层

ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS course_map JSONB;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS course_map_validated BOOLEAN DEFAULT FALSE;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS course_map_issues JSONB;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS calibration_routing JSONB;

COMMENT ON COLUMN skill_blueprints.course_map IS '课程地图：章节顺序、课型、学习目标、知识点覆盖、Bloom分布';
COMMENT ON COLUMN skill_blueprints.course_map_validated IS 'Course Map 是否通过7项自动校验';
COMMENT ON COLUMN skill_blueprints.course_map_issues IS 'Course Map 校验发现的问题列表';
COMMENT ON COLUMN skill_blueprints.calibration_routing IS '经验校准数据到章节的路由分配映射';
