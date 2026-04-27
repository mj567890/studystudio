-- Phase 3：tutorial_skeletons 加 space_id 列，约束改为 (space_id, topic_key) 联合唯一

BEGIN;

-- 1. 加 space_id 列（允许 NULL，孤立数据保持 NULL）
ALTER TABLE tutorial_skeletons
    ADD COLUMN space_id uuid REFERENCES knowledge_spaces(space_id) ON DELETE SET NULL;

-- 2. 回填能匹配到的 space_id
UPDATE tutorial_skeletons ts
SET space_id = sb.space_id
FROM skill_blueprints sb
WHERE sb.topic_key = ts.topic_key
  AND sb.space_id IS NOT NULL;

-- 3. Phase2测试空间 单独回填（有 space 但无 blueprint）
UPDATE tutorial_skeletons
SET space_id = '04a73568-452d-4320-ac92-104dddb8e123'
WHERE topic_key = 'Phase2测试空间' AND space_id IS NULL;

-- 4. 删除旧的单列唯一约束
ALTER TABLE tutorial_skeletons DROP CONSTRAINT uq_skeleton_topic;

-- 5. 新增联合唯一约束（NULL 不等于 NULL，孤立数据不会互相冲突）
ALTER TABLE tutorial_skeletons ADD CONSTRAINT uq_skeleton_space_topic
    UNIQUE (space_id, topic_key);

COMMIT;
