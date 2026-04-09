DROP TABLE IF EXISTS chapter_entity_links  CASCADE;
DROP TABLE IF EXISTS skill_chapter_edges   CASCADE;
DROP TABLE IF EXISTS skill_chapters        CASCADE;
DROP TABLE IF EXISTS skill_stages          CASCADE;
DROP TABLE IF EXISTS skill_blueprints      CASCADE;
DO $$ BEGIN RAISE NOTICE '✓ 5 张表已删除'; END $$;
