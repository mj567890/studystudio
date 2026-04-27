-- 022_schema_migrations: 迁移追踪表
-- 记录已执行的迁移文件，支持增量升级

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 标记当前所有迁移为已应用（新装场景：这些迁移都在本次安装中执行）
INSERT INTO schema_migrations (filename)
VALUES
    ('001_initial_schema.sql'),
    ('002_ai_config.sql'),
    ('003_social_learning_phase1.sql'),
    ('005_space_subscriptions.sql'),
    ('006_phase3_topic_key_fork.sql'),
    ('007_tutorial_skeletons_space_id.sql'),
    ('008_community_curations.sql'),
    ('009_fork_space.sql'),
    ('010_account_deactivation.sql'),
    ('011_wall_posts_space_id.sql'),
    ('012_blueprint_failed_status.sql'),
    ('013_course_posts.sql'),
    ('014_fix_document_status_check.sql'),
    ('015_eight_dim_tables.sql'),
    ('016_course_posts.sql'),
    ('017_add_page_no_to_document_chunks.sql'),
    ('018_task_executions_and_audit.sql'),
    ('019_user_notifications.sql'),
    ('020_note_entity_links.sql'),
    ('021_chapter_content_columns.sql')
ON CONFLICT (filename) DO NOTHING;
