-- Migration 013: 课程讨论区
-- course_posts + course_post_replies

CREATE TABLE course_posts (
    post_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    space_id      UUID NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    chapter_id    UUID REFERENCES skill_chapters(chapter_id) ON DELETE SET NULL,
    user_id       UUID NOT NULL REFERENCES users(user_id),
    post_type     VARCHAR(20) NOT NULL DEFAULT 'discussion'
                  CHECK (post_type IN ('note', 'question', 'discussion')),
    title         VARCHAR(255),
    content       TEXT NOT NULL,
    reply_count   INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE course_post_replies (
    reply_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id    UUID NOT NULL REFERENCES course_posts(post_id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(user_id),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_course_posts_space ON course_posts(space_id, created_at DESC);
CREATE INDEX idx_course_posts_chapter ON course_posts(chapter_id) WHERE chapter_id IS NOT NULL;
CREATE INDEX idx_course_post_replies_post ON course_post_replies(post_id, created_at);
