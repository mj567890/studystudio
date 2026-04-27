-- 020_note_entity_links.sql
-- Phase 9.2：笔记→知识实体关联表
-- 记笔记时自动关联当前章节的知识实体，支持"按知识点查看所有笔记"

CREATE TABLE IF NOT EXISTS note_entity_links (
    note_id    UUID NOT NULL,
    entity_id  UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_note_entity PRIMARY KEY (note_id, entity_id),
    CONSTRAINT fk_note_entity_note   FOREIGN KEY (note_id)   REFERENCES learner_notes(note_id)     ON DELETE CASCADE,
    CONSTRAINT fk_note_entity_entity FOREIGN KEY (entity_id) REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_note_entity_entity ON note_entity_links(entity_id);
CREATE INDEX IF NOT EXISTS idx_note_entity_note   ON note_entity_links(note_id);
