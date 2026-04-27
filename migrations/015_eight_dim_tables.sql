-- migrations/015_eight_dim_tables.sql
-- 八维度学习增强系统缺失表创建
-- 创建日期: 2026-04-24

BEGIN;

-- ═══════════════════════════════════════════════
-- D6: 学习节奏偏好
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS learner_learning_mode (
    user_id    UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    read_mode  VARCHAR(20) NOT NULL DEFAULT 'normal'
               CHECK (read_mode IN ('skim', 'normal', 'deep')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════════════════════════
-- D7: 章末反思
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS chapter_reflections (
    user_id       UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    chapter_id    VARCHAR(50) NOT NULL,
    own_example   TEXT NOT NULL DEFAULT '',
    misconception TEXT NOT NULL DEFAULT '',
    ai_feedback   JSONB,
    ai_score      FLOAT DEFAULT 0.0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, chapter_id)
);

-- ═══════════════════════════════════════════════
-- D8: 成就系统
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS learner_achievements (
    achievement_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    achievement_type VARCHAR(50) NOT NULL,
    achievement_name VARCHAR(255) NOT NULL,
    ref_id           VARCHAR(100),
    payload          JSONB DEFAULT '{}',
    earned_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_achievements_user
    ON learner_achievements(user_id, earned_at DESC);

-- ═══════════════════════════════════════════════
-- H-6: 章节测验答题记录（错题模式分析）
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS chapter_quiz_attempts (
    attempt_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id           UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    chapter_id        VARCHAR(50) NOT NULL,
    wrong_entity_ids  JSONB DEFAULT '[]',
    score             FLOAT DEFAULT 0.0,
    attempted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user
    ON chapter_quiz_attempts(user_id, attempted_at DESC);

-- ═══════════════════════════════════════════════
-- 学习墙：帖子
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS wall_posts (
    post_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    chapter_id  VARCHAR(50) NOT NULL,
    topic_key   VARCHAR(100) NOT NULL DEFAULT '',
    space_id    UUID REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    post_type   VARCHAR(20) NOT NULL DEFAULT 'stuck'
                CHECK (post_type IN ('stuck', 'tip', 'discuss')),
    content     TEXT NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'resolved')),
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    likes       INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wall_posts_space ON wall_posts(space_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wall_posts_chapter ON wall_posts(chapter_id);

-- ═══════════════════════════════════════════════
-- 学习墙：回复
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS wall_replies (
    reply_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id    UUID NOT NULL REFERENCES wall_posts(post_id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    is_ai      BOOLEAN NOT NULL DEFAULT FALSE,
    likes      INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wall_replies_post ON wall_replies(post_id, created_at);

-- ═══════════════════════════════════════════════
-- 个人笔记
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS learner_notes (
    note_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    notebook_id     UUID,
    title           VARCHAR(255),
    content         TEXT NOT NULL,
    source_type     VARCHAR(20) NOT NULL DEFAULT 'manual'
                    CHECK (source_type IN ('manual', 'ai_chat')),
    topic_key       VARCHAR(100) NOT NULL DEFAULT '',
    chapter_id      VARCHAR(50) NOT NULL DEFAULT '',
    chapter_title   VARCHAR(255) NOT NULL DEFAULT '',
    conversation_id VARCHAR(100) NOT NULL DEFAULT '',
    tags            JSONB DEFAULT '[]',
    review_count    INTEGER NOT NULL DEFAULT 0,
    next_review_at  TIMESTAMPTZ,
    last_reviewed_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_learner_notes_user ON learner_notes(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_learner_notes_notebook ON learner_notes(notebook_id);

-- ═══════════════════════════════════════════════
-- 笔记本
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS learner_notebooks (
    notebook_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    topic_key   VARCHAR(100) NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_learner_notebooks_user ON learner_notebooks(user_id);

-- 添加外键：learner_notes.notebook_id → learner_notebooks
ALTER TABLE learner_notes
    ADD CONSTRAINT fk_learner_notes_notebook
    FOREIGN KEY (notebook_id) REFERENCES learner_notebooks(notebook_id) ON DELETE SET NULL;

COMMIT;
