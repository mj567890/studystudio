-- Phase 3 Fork: topic_key 唯一约束从单列改为 (space_id, topic_key) 联合唯一
-- 前提：skill_blueprints.space_id 无空值，且无跨 space 重名 topic_key

BEGIN;

-- 1. 删除旧的单列唯一约束
ALTER TABLE skill_blueprints DROP CONSTRAINT uq_blueprint_topic;

-- 2. space_id 改为非空
ALTER TABLE skill_blueprints ALTER COLUMN space_id SET NOT NULL;

-- 3. 新增联合唯一约束
ALTER TABLE skill_blueprints ADD CONSTRAINT uq_blueprint_space_topic
    UNIQUE (space_id, topic_key);

COMMIT;
