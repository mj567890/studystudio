-- Migration 010: 账号注销软删除
-- 将 users.status CHECK 约束扩展，加入 deleted 值
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_status_check;
ALTER TABLE users ADD CONSTRAINT users_status_check
  CHECK (status::text = ANY (ARRAY['active'::text, 'disabled'::text, 'deleted'::text]));
