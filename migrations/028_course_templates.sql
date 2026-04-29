-- 028_course_templates.sql
-- 课程模板：教师可保存和复用的教学指令模板
-- 日期：2026-04-29

BEGIN;

-- 1. 模板表
CREATE TABLE IF NOT EXISTS course_templates (
    template_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         VARCHAR(100) NOT NULL,
    content      TEXT NOT NULL,
    is_system    BOOLEAN NOT NULL DEFAULT FALSE,
    is_public    BOOLEAN NOT NULL DEFAULT FALSE,
    created_by   UUID REFERENCES users(user_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引：按创建者查询用户自定义模板
CREATE INDEX IF NOT EXISTS idx_course_templates_created_by
    ON course_templates(created_by) WHERE created_by IS NOT NULL;

-- 索引：系统默认 + 公开模板列表
CREATE INDEX IF NOT EXISTS idx_course_templates_system_public
    ON course_templates(template_id) WHERE is_system = TRUE OR is_public = TRUE;

-- 2. 知识空间：默认课程模板
ALTER TABLE knowledge_spaces
    ADD COLUMN IF NOT EXISTS default_template_id UUID
    REFERENCES course_templates(template_id) ON DELETE SET NULL;

-- 3. 系统默认模板（4 条）
INSERT INTO course_templates (name, content, is_system, is_public) VALUES
(
    '标准教程',
    '请生成标准的职业技能教程：理论讲解与实操案例并重，每章包含概念阐述、代码示例和常见误区。语言风格正式专业，适合高等教育或企业培训场景。',
    TRUE, TRUE
),
(
    '实操导向',
    '请侧重实践操作和项目驱动：减少理论推导篇幅，增加完整代码示例和动手练习。每章应以真实工作任务为引子，让学员"边做边学"。适合中职、高职或企业技能培训。',
    TRUE, TRUE
),
(
    '理论基础',
    '请深入讲解概念原理和底层机制：优先说清楚"为什么"，辅以示意图逻辑和对比分析。代码示例仅用于说明原理，不要求完整项目。适合研究型或考证备考学员。',
    TRUE, TRUE
),
(
    '速成精简',
    '请精简内容至核心要点：每章控制在400字以内，跳过推导过程，直接给出结论和操作步骤。使用清单式、分点式表达，减少段落叙述。适合快速入门或考前突击。',
    TRUE, TRUE
);

-- 4. 迁移记录
INSERT INTO schema_migrations (filename, applied_at) VALUES ('028_course_templates.sql', NOW());

COMMIT;
