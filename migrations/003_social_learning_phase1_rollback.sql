-- migrations/003_social_learning_phase1_rollback.sql
-- 回滚 Phase 1 社交学习迁移
BEGIN;
DROP TABLE  IF EXISTS space_members;
DROP INDEX  IF EXISTS uq_knowledge_spaces_invite_code;
ALTER TABLE knowledge_spaces DROP CONSTRAINT IF EXISTS knowledge_spaces_visibility_check;
ALTER TABLE knowledge_spaces DROP COLUMN     IF EXISTS visibility;
ALTER TABLE knowledge_spaces DROP COLUMN     IF EXISTS invite_code;
ALTER TABLE knowledge_spaces DROP COLUMN     IF EXISTS updated_at;
COMMIT;
