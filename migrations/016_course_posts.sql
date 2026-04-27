-- migrations/016_course_posts.sql
-- 课程讨论区表（原 migration 013 因 skill_chapters FK 引用失败而重新创建）

BEGIN;

CREATE TABLE IF NOT EXISTS course_posts (
    post_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    space_id      UUID NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    chapter_id    UUID,  -- 暂不引用 skill_chapters（表已废弃），后续迁移到 tutorial_contents
    user_id       UUID NOT NULL REFERENCES users(user_id),
    post_type     VARCHAR(20) NOT NULL DEFAULT 'discussion'
                  CHECK (post_type IN ('note', 'question', 'discussion')),
    title         VARCHAR(255),
    content       TEXT NOT NULL,
    reply_count   INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS course_post_replies (
    reply_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id    UUID NOT NULL REFERENCES course_posts(post_id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(user_id),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_course_posts_space ON course_posts(space_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_course_posts_chapter ON course_posts(chapter_id) WHERE chapter_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_course_post_replies_post ON course_post_replies(post_id, created_at);

COMMIT;
