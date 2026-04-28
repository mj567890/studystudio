-- =============================================================================
-- 迁移 026：衍生表 chapter_id 类型标准化 + FK 约束补齐
-- 说明：9 张衍生表的 chapter_id 列部分为 VARCHAR，无法与 skill_chapters
--       (UUID) 建立 FK。本次统一转换为 UUID 并添加外键约束。
-- 风险：若表中有非法 UUID 数据，ALTER 会失败。需先跑诊断 SQL 清洗。
-- 诊断：当前开发环境全部表无孤儿数据，可安全执行。
-- 创建时间：2026-04-28
-- =============================================================================

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════
-- 1. 类型标准化（VARCHAR → UUID）
--    使用 USING chapter_id::uuid 转换。
--    已确认：chapter_entity_links(258行,0孤儿), 其余各表均为空。
-- ═══════════════════════════════════════════════════════════════════════

-- 1a. chapter_quiz_attempts
ALTER TABLE chapter_quiz_attempts
    ALTER COLUMN chapter_id TYPE UUID USING chapter_id::uuid;

-- 1b. chapter_progress
ALTER TABLE chapter_progress
    ALTER COLUMN chapter_id TYPE UUID USING chapter_id::uuid;

-- 1c. chapter_reflections
ALTER TABLE chapter_reflections
    ALTER COLUMN chapter_id TYPE UUID USING chapter_id::uuid;

-- 1d. wall_posts
ALTER TABLE wall_posts
    ALTER COLUMN chapter_id TYPE UUID USING chapter_id::uuid;

-- 1e. learner_notes（默认值为空字符串，需先 DROP DEFAULT + DROP NOT NULL）
ALTER TABLE learner_notes
    ALTER COLUMN chapter_id DROP DEFAULT,
    ALTER COLUMN chapter_id DROP NOT NULL,
    ALTER COLUMN chapter_id TYPE UUID USING NULLIF(chapter_id, '')::uuid;

-- 1f. tutorial_annotations
ALTER TABLE tutorial_annotations
    ALTER COLUMN chapter_id TYPE UUID USING chapter_id::uuid;

-- 1g. tutorial_contents
ALTER TABLE tutorial_contents
    ALTER COLUMN chapter_id TYPE UUID USING chapter_id::uuid;

-- 以下两表 chapter_id 已是 UUID，跳过转换：
--   course_posts, chapter_entity_links

-- ═══════════════════════════════════════════════════════════════════════
-- 2. 外键约束（ON DELETE CASCADE）
--    章节删除 → 全部关联数据自动清理
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE chapter_quiz_attempts
    ADD CONSTRAINT fk_quiz_attempts_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE CASCADE;

ALTER TABLE chapter_progress
    ADD CONSTRAINT fk_progress_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE CASCADE;

ALTER TABLE chapter_reflections
    ADD CONSTRAINT fk_reflections_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE CASCADE;

ALTER TABLE course_posts
    ADD CONSTRAINT fk_course_posts_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE CASCADE;

ALTER TABLE wall_posts
    ADD CONSTRAINT fk_wall_posts_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE CASCADE;

ALTER TABLE learner_notes
    ADD CONSTRAINT fk_learner_notes_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE SET NULL;

ALTER TABLE tutorial_annotations
    ADD CONSTRAINT fk_tutorial_annotations_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE CASCADE;

ALTER TABLE tutorial_contents
    ADD CONSTRAINT fk_tutorial_contents_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE CASCADE;

ALTER TABLE chapter_entity_links
    ADD CONSTRAINT fk_chapter_entity_links_chapter
        FOREIGN KEY (chapter_id) REFERENCES skill_chapters(chapter_id)
        ON DELETE CASCADE;

-- ═══════════════════════════════════════════════════════════════════════
-- 3. 索引（加速级联删除和 JOIN 查询）
-- ═══════════════════════════════════════════════════════════════════════

CREATE INDEX IF NOT EXISTS idx_quiz_attempts_chapter
    ON chapter_quiz_attempts(chapter_id);
CREATE INDEX IF NOT EXISTS idx_progress_chapter
    ON chapter_progress(chapter_id);
CREATE INDEX IF NOT EXISTS idx_reflections_chapter
    ON chapter_reflections(chapter_id);
CREATE INDEX IF NOT EXISTS idx_course_posts_chapter
    ON course_posts(chapter_id);
CREATE INDEX IF NOT EXISTS idx_wall_posts_chapter
    ON wall_posts(chapter_id);
CREATE INDEX IF NOT EXISTS idx_learner_notes_chapter
    ON learner_notes(chapter_id);
CREATE INDEX IF NOT EXISTS idx_tutorial_annotations_chapter
    ON tutorial_annotations(chapter_id);
CREATE INDEX IF NOT EXISTS idx_tutorial_contents_chapter
    ON tutorial_contents(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chapter_entity_links_chapter
    ON chapter_entity_links(chapter_id);

-- ═══════════════════════════════════════════════════════════════════════
-- 4. 回滚说明
-- ═══════════════════════════════════════════════════════════════════════
-- 回滚脚本（如需）：
--   先删 FK → 再改回 VARCHAR:
--   ALTER TABLE chapter_entity_links DROP CONSTRAINT IF EXISTS fk_chapter_entity_links_chapter;
--   ... (其他 8 个同理)
--   ALTER TABLE tutorial_contents ALTER COLUMN chapter_id TYPE VARCHAR;
--   ... (其他 6 个 VARCHAR 表同理)

COMMIT;
