-- Phase 4：公共社区策展表

BEGIN;

CREATE TABLE community_curations (
    curation_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id    UUID NOT NULL REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE,
    space_id     UUID NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    curated_by   UUID REFERENCES users(user_id) ON DELETE SET NULL,
    curated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status       VARCHAR(20) NOT NULL DEFAULT 'pending',
    tags         JSONB NOT NULL DEFAULT '[]',
    note         TEXT,
    CONSTRAINT uq_curation_entity_space UNIQUE (entity_id, space_id),
    CONSTRAINT community_curations_status_check
        CHECK (status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX idx_curation_space    ON community_curations (space_id);
CREATE INDEX idx_curation_status   ON community_curations (status);
CREATE INDEX idx_curation_entity   ON community_curations (entity_id);

COMMIT;
