-- migrations/001_initial_schema.sql
-- 自适应学习平台完整数据库 Schema
-- 基于总纲 V2.6 / 细节 V2.6 数据结构设计

-- ═══════════════════════════════════════════════
-- 扩展
-- ═══════════════════════════════════════════════
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ═══════════════════════════════════════════════
-- 用户与权限域
-- ═══════════════════════════════════════════════
CREATE TABLE users (
    user_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nickname      VARCHAR(100),
    avatar_url    TEXT,
    status        VARCHAR(20) NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'disabled')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE roles (
    role_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_name  VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE permissions (
    permission_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    permission_code VARCHAR(100) UNIQUE NOT NULL,
    description     TEXT
);

CREATE TABLE user_roles (
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(role_id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE role_permissions (
    role_id       UUID REFERENCES roles(role_id) ON DELETE CASCADE,
    permission_id UUID REFERENCES permissions(permission_id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- 初始化基础角色
INSERT INTO roles (role_name) VALUES
    ('learner'), ('teacher'), ('content_editor'), ('knowledge_reviewer'), ('admin');

-- ═══════════════════════════════════════════════
-- 文件与文档域
-- ═══════════════════════════════════════════════
CREATE TABLE files (
    file_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_name   VARCHAR(255) NOT NULL,
    file_type   VARCHAR(20) NOT NULL,
    file_size   BIGINT NOT NULL,
    file_hash   VARCHAR(64) UNIQUE NOT NULL,  -- SHA-256，用于去重
    storage_url TEXT NOT NULL,
    uploaded_by UUID REFERENCES users(user_id),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_files_hash ON files(file_hash);

CREATE TABLE documents (
    document_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_id         UUID REFERENCES files(file_id),
    title           VARCHAR(255) NOT NULL,
    source_type     VARCHAR(30) NOT NULL DEFAULT 'upload',
    document_status VARCHAR(30) NOT NULL DEFAULT 'uploaded'
                    CHECK (document_status IN ('uploaded','parsed','extracted','reviewed','published')),
    space_type      VARCHAR(20) NOT NULL DEFAULT 'global'
                    CHECK (space_type IN ('global','course','personal')),
    space_id        UUID,
    owner_id        UUID REFERENCES users(user_id),
    language        VARCHAR(20) DEFAULT 'zh',
    chunk_count     INTEGER DEFAULT 0,
    is_truncated    BOOLEAN NOT NULL DEFAULT FALSE,
    original_chunk_count INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_documents_owner ON documents(owner_id);
CREATE INDEX idx_documents_space ON documents(space_type, space_id);

CREATE TABLE document_chunks (
    chunk_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id   UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    index_no      INTEGER NOT NULL,
    title_path    JSONB,
    content       TEXT NOT NULL,
    token_count   INTEGER,
    start_offset  INTEGER,
    end_offset    INTEGER,
    embedding     VECTOR(1536)
);
CREATE INDEX idx_chunks_document ON document_chunks(document_id, index_no);
CREATE INDEX idx_chunks_embedding ON document_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ═══════════════════════════════════════════════
-- 知识空间域
-- ═══════════════════════════════════════════════
CREATE TABLE knowledge_spaces (
    space_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    space_type  VARCHAR(20) NOT NULL CHECK (space_type IN ('global','course','personal')),
    owner_id    UUID REFERENCES users(user_id),
    name        VARCHAR(255),
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════════════════════════
-- 知识域
-- ═══════════════════════════════════════════════
CREATE TABLE knowledge_entities (
    entity_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                 VARCHAR(255) NOT NULL,
    entity_type          VARCHAR(30) NOT NULL
                         CHECK (entity_type IN ('concept','element','flow','case','defense')),
    canonical_name       VARCHAR(255) NOT NULL,
    domain_tag           VARCHAR(100) NOT NULL,
    space_type           VARCHAR(20) NOT NULL DEFAULT 'global'
                         CHECK (space_type IN ('global','course','personal')),
    space_id             UUID,
    owner_id             UUID REFERENCES users(user_id),
    visibility           VARCHAR(20) NOT NULL DEFAULT 'public'
                         CHECK (visibility IN ('public','course','private')),
    short_definition     TEXT,
    detailed_explanation TEXT,
    review_status        VARCHAR(20) NOT NULL DEFAULT 'pending'
                         CHECK (review_status IN ('pending','approved','rejected')),
    is_core              BOOLEAN NOT NULL DEFAULT FALSE,
    embedding            VECTOR(1536),
    version              INTEGER NOT NULL DEFAULT 1,
    aliases              JSONB DEFAULT '[]',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_entity_space_domain_status
    ON knowledge_entities(space_type, domain_tag, review_status);
CREATE INDEX idx_entity_canonical ON knowledge_entities(canonical_name);
CREATE INDEX idx_entity_embedding ON knowledge_entities
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE knowledge_relations (
    relation_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_entity_id UUID NOT NULL REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE,
    relation_type   VARCHAR(50) NOT NULL,  -- prerequisite_of / related / part_of / instance_of
    weight          FLOAT NOT NULL DEFAULT 1.0,
    review_status   VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_relation_source ON knowledge_relations(source_entity_id);
CREATE INDEX idx_relation_target ON knowledge_relations(target_entity_id);

CREATE TABLE personal_entity_references (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    ref_entity_id  UUID NOT NULL REFERENCES knowledge_entities(entity_id),
    personal_note  TEXT,
    source_doc_id  UUID REFERENCES documents(document_id),
    candidate_snapshot JSONB,  -- 原始候选实体字段快照，防止信息丢失
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════════════════════════
-- 学习者画像域
-- ═══════════════════════════════════════════════
CREATE TABLE learner_profiles (
    user_id         UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    mastery_summary JSONB NOT NULL DEFAULT '{}',
    version         INTEGER NOT NULL DEFAULT 0,   -- 乐观锁版本号
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE learner_knowledge_states (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    entity_id      UUID NOT NULL REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE,
    mastery_score  FLOAT NOT NULL DEFAULT 0.0 CHECK (mastery_score BETWEEN 0 AND 1),
    decay_rate     FLOAT NOT NULL DEFAULT 0.1,
    last_reviewed_at TIMESTAMPTZ,
    review_count   INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, entity_id)
);
CREATE INDEX idx_learner_state_user_entity
    ON learner_knowledge_states(user_id, entity_id);
CREATE INDEX idx_learner_state_score ON learner_knowledge_states(user_id, mastery_score);

CREATE TABLE placement_question_banks (
    bank_id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic_key           VARCHAR(100) NOT NULL UNIQUE,
    questions_by_domain JSONB NOT NULL DEFAULT '{}',
    is_ready            BOOLEAN NOT NULL DEFAULT FALSE,
    built_at            TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_placement_bank_topic ON placement_question_banks(topic_key);

-- ═══════════════════════════════════════════════
-- 教程域
-- ═══════════════════════════════════════════════
CREATE TABLE tutorial_skeletons (
    skeleton_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tutorial_id    UUID NOT NULL,
    topic_key      VARCHAR(100) NOT NULL,
    chapter_tree   JSONB NOT NULL DEFAULT '[]',
    status         VARCHAR(20) NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft','approved')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_skeleton_topic UNIQUE (topic_key)  -- D2：幂等写入约束
);

CREATE TABLE tutorial_contents (
    content_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tutorial_id    UUID NOT NULL,
    chapter_id     VARCHAR(50) NOT NULL,
    content_text   TEXT NOT NULL,
    quality_scores JSONB,
    llm_coherence_ref FLOAT,   -- LLM 辅助连贯性评分（仅参考）
    status         VARCHAR(30) NOT NULL DEFAULT 'pending_review',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_content_tutorial ON tutorial_contents(tutorial_id, chapter_id);

CREATE TABLE tutorial_annotations (
    annotation_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tutorial_id    UUID NOT NULL,
    user_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    chapter_id     VARCHAR(50) NOT NULL,
    gap_types      JSONB DEFAULT '[]',
    priority_boost FLOAT DEFAULT 0.0,
    is_weak_point  BOOLEAN DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tutorial_id, user_id, chapter_id)
);

-- ═══════════════════════════════════════════════
-- 对话域
-- ═══════════════════════════════════════════════
CREATE TABLE conversations (
    conversation_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    topic_key       VARCHAR(100) NOT NULL,
    turn_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE conversation_turns (
    turn_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role            VARCHAR(10) NOT NULL CHECK (role IN ('user','assistant')),
    content         TEXT NOT NULL,
    gap_type        VARCHAR(30),
    error_pattern   TEXT,
    understood      BOOLEAN,
    cited_entity_ids JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_turns_conversation ON conversation_turns(conversation_id, created_at);

-- ═══════════════════════════════════════════════
-- 审核域
-- ═══════════════════════════════════════════════
CREATE TABLE extract_audit (
    audit_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id    UUID,
    step        VARCHAR(50) NOT NULL,
    error       TEXT,
    raw_output  TEXT,
    status      VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE entity_normalize_audit (
    audit_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id     UUID,
    similar_entity_id UUID,
    similarity_score  FLOAT,
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    decision          VARCHAR(20),
    reviewed_by       UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════════════════════════
-- 事件幂等表
-- ═══════════════════════════════════════════════
CREATE TABLE event_idempotency (
    consumer_id  VARCHAR(100) NOT NULL,
    event_id     UUID NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (consumer_id, event_id)
);
CREATE UNIQUE INDEX idx_event_idempotency_unique
    ON event_idempotency(consumer_id, event_id);

-- ═══════════════════════════════════════════════
-- 知识抽取临时表（用于归一处理前的暂存）
-- ═══════════════════════════════════════════════
CREATE TABLE knowledge_entities_temp (LIKE knowledge_entities INCLUDING ALL);
CREATE TABLE knowledge_relations_temp (LIKE knowledge_relations INCLUDING ALL);

-- ═══════════════════════════════════════════════
-- 前端补充开发新增表（V1.4 补充）
-- ═══════════════════════════════════════════════

-- 章节学习进度
CREATE TABLE IF NOT EXISTS chapter_progress (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tutorial_id     VARCHAR(100) NOT NULL,
    chapter_id      VARCHAR(100) NOT NULL,
    completed       BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, tutorial_id, chapter_id)
);
CREATE INDEX idx_chapter_progress_user ON chapter_progress(user_id, tutorial_id);

-- 系统配置（替代修改.env文件）
CREATE TABLE IF NOT EXISTS system_configs (
    config_key      VARCHAR(100) PRIMARY KEY,
    config_value    TEXT NOT NULL,
    description     TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 初始化默认配置
INSERT INTO system_configs (config_key, config_value, description) VALUES
    ('llm_default_model',   'deepseek-chat',  'LLM 默认模型'),
    ('daily_token_budget',  '2000000',        '每日 Token 预算'),
    ('max_chunk_count',     '500',            '单文档最大分块数'),
    ('init_completed',      'false',          '系统初始化是否完成')
ON CONFLICT DO NOTHING;
