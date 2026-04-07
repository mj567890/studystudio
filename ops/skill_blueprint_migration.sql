BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS skill_blueprints (
    blueprint_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_key TEXT NOT NULL,
    space_type TEXT NOT NULL DEFAULT 'personal',
    space_id UUID NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    skill_goal TEXT NOT NULL DEFAULT '',
    target_role TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    source_fingerprint TEXT NOT NULL DEFAULT '',
    source_entity_count INTEGER NOT NULL DEFAULT 0,
    published_at TIMESTAMPTZ NULL,
    created_by UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (topic_key, space_type, version)
);

CREATE INDEX IF NOT EXISTS idx_skill_blueprints_topic_status
ON skill_blueprints (topic_key, space_type, status, version DESC);

CREATE TABLE IF NOT EXISTS skill_stages (
    stage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blueprint_id UUID NOT NULL REFERENCES skill_blueprints(blueprint_id) ON DELETE CASCADE,
    stage_order INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    objective TEXT NOT NULL DEFAULT '',
    can_do_after TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_stages_blueprint_order
ON skill_stages (blueprint_id, stage_order);

CREATE TABLE IF NOT EXISTS skill_chapters (
    chapter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blueprint_id UUID NOT NULL REFERENCES skill_blueprints(blueprint_id) ON DELETE CASCADE,
    stage_id UUID NOT NULL REFERENCES skill_stages(stage_id) ON DELETE CASCADE,
    chapter_order INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    objective TEXT NOT NULL DEFAULT '',
    can_do_after TEXT NOT NULL DEFAULT '',
    practice_task TEXT NOT NULL DEFAULT '',
    pass_criteria TEXT NOT NULL DEFAULT '',
    estimated_minutes INTEGER NOT NULL DEFAULT 30,
    learning_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    glossary_entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_chapters_blueprint_order
ON skill_chapters (blueprint_id, chapter_order);

CREATE TABLE IF NOT EXISTS skill_chapter_edges (
    edge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blueprint_id UUID NOT NULL REFERENCES skill_blueprints(blueprint_id) ON DELETE CASCADE,
    from_chapter_id UUID NOT NULL REFERENCES skill_chapters(chapter_id) ON DELETE CASCADE,
    to_chapter_id UUID NOT NULL REFERENCES skill_chapters(chapter_id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL DEFAULT 'prerequisite',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (from_chapter_id, to_chapter_id, edge_type)
);

CREATE TABLE IF NOT EXISTS chapter_entity_links (
    link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blueprint_id UUID NOT NULL REFERENCES skill_blueprints(blueprint_id) ON DELETE CASCADE,
    chapter_id UUID NOT NULL REFERENCES skill_chapters(chapter_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL,
    link_role TEXT NOT NULL DEFAULT 'glossary',
    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (chapter_id, entity_id, link_role)
);

CREATE TABLE IF NOT EXISTS skill_blueprint_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_key TEXT NOT NULL,
    space_type TEXT NOT NULL DEFAULT 'personal',
    space_id UUID NULL,
    requested_by UUID NULL,
    job_status TEXT NOT NULL DEFAULT 'queued',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ NULL
);

ALTER TABLE tutorial_skeletons
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE tutorial_contents
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE OR REPLACE VIEW v_skill_blueprint_topic_stats AS
SELECT
    sb.topic_key,
    sb.space_type,
    sb.space_id,
    sb.blueprint_id,
    sb.version,
    sb.status,
    sb.skill_goal,
    sb.summary,
    sb.updated_at,
    COALESCE(ch.chapter_count, 0) AS chapter_count,
    COALESCE(ent.approved_entity_count, 0) AS approved_entity_count
FROM skill_blueprints sb
LEFT JOIN (
    SELECT blueprint_id, COUNT(*) AS chapter_count
    FROM skill_chapters
    GROUP BY blueprint_id
) ch ON ch.blueprint_id = sb.blueprint_id
LEFT JOIN (
    SELECT domain_tag, COUNT(*) AS approved_entity_count
    FROM knowledge_entities
    WHERE review_status = 'approved'
    GROUP BY domain_tag
) ent ON ent.domain_tag = sb.topic_key;

COMMIT;
