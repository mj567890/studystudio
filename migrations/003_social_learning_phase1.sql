-- migrations/003_social_learning_phase1.sql
-- 社交学习 Phase 1:多成员 space + 邀请码 + visibility
-- 2026-04-15

BEGIN;

-- knowledge_spaces 新增三列
ALTER TABLE knowledge_spaces
    ADD COLUMN IF NOT EXISTS visibility  varchar(20) NOT NULL DEFAULT 'private',
    ADD COLUMN IF NOT EXISTS invite_code varchar(32),
    ADD COLUMN IF NOT EXISTS updated_at  timestamptz NOT NULL DEFAULT now();

-- visibility 取值约束
ALTER TABLE knowledge_spaces
    DROP CONSTRAINT IF EXISTS knowledge_spaces_visibility_check;
ALTER TABLE knowledge_spaces
    ADD  CONSTRAINT knowledge_spaces_visibility_check
    CHECK (visibility IN ('private','shared','public'));

-- invite_code 全局唯一(NULL 不受约束)
CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_spaces_invite_code
    ON knowledge_spaces(invite_code)
    WHERE invite_code IS NOT NULL;

COMMENT ON COLUMN knowledge_spaces.visibility  IS 'private=仅 owner 可见;shared=成员可见;public=Phase 4 社区策展预留';
COMMENT ON COLUMN knowledge_spaces.invite_code IS '邀请码。shared 空间用,通过 /join/{code} 加入';

-- space_members:空间成员关系
CREATE TABLE IF NOT EXISTS space_members (
    space_id   uuid        NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    user_id    uuid        NOT NULL REFERENCES users(user_id)             ON DELETE CASCADE,
    role       varchar(20) NOT NULL DEFAULT 'member',
    joined_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (space_id, user_id),
    CONSTRAINT space_members_role_check CHECK (role IN ('owner','admin','member'))
);

CREATE INDEX IF NOT EXISTS idx_space_members_user ON space_members(user_id);

COMMENT ON TABLE  space_members IS '知识空间成员关系。owner 也在此表登记一行,方便统一权限查询。';
COMMENT ON COLUMN space_members.role IS 'owner=创建者;admin=协管(Phase 1 暂无特权,预留);member=普通成员';

-- 回填:现存 space 的 owner_id 插入 space_members(role=owner)
INSERT INTO space_members (space_id, user_id, role, joined_at)
SELECT space_id, owner_id, 'owner', created_at
FROM   knowledge_spaces
WHERE  owner_id IS NOT NULL
ON CONFLICT (space_id, user_id) DO NOTHING;

COMMIT;
