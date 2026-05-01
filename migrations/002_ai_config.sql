-- migrations/002_ai_config.sql
-- Phase 0：AI 配置管理（providers + capability bindings）
-- 2026-04-13

BEGIN;

-- ─────────────────────────────────────────────────────────────
-- ai_providers：第三方 AI 服务连接信息
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_providers (
    provider_id       uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    name              varchar(100) UNIQUE NOT NULL,
    kind              varchar(30)  NOT NULL,
    base_url          text         NOT NULL,
    api_key_encrypted text,
    extra_config      jsonb        NOT NULL DEFAULT '{}'::jsonb,
    enabled           boolean      NOT NULL DEFAULT true,
    last_tested_at    timestamptz,
    last_test_ok      boolean,
    last_test_error   text,
    created_at        timestamptz  NOT NULL DEFAULT now(),
    updated_at        timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT ai_providers_kind_check CHECK (kind IN
        ('openai_compatible','anthropic','gemini','ollama','azure_openai','image_api','image_local'))
);

COMMENT ON TABLE  ai_providers IS 'AI 服务提供方连接配置。api_key 用 Fernet 加密存储。';
COMMENT ON COLUMN ai_providers.kind IS '协议类型。当前全部走 openai_compatible；anthropic/gemini/ollama/azure_openai 作为扩展占位。';
COMMENT ON COLUMN ai_providers.extra_config IS '协议特有参数。如 azure 的 api_version、anthropic 的 anthropic_version 等。';

-- ─────────────────────────────────────────────────────────────
-- ai_capability_bindings：能力 → provider 路由表
-- 每个能力可有多个 priority 级别（0=主，1,2,... 依次兜底）
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_capability_bindings (
    binding_id   uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    capability   varchar(60)  NOT NULL,
    provider_id  uuid         NOT NULL REFERENCES ai_providers(provider_id) ON DELETE CASCADE,
    model_name   varchar(200) NOT NULL,
    priority     int          NOT NULL DEFAULT 0,
    params       jsonb        NOT NULL DEFAULT '{}'::jsonb,
    enabled      boolean      NOT NULL DEFAULT true,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT ai_capability_bindings_priority_unique UNIQUE (capability, priority)
);

COMMENT ON TABLE  ai_capability_bindings IS '能力 → provider 路由表。按 priority ASC 从主到备。';
COMMENT ON COLUMN ai_capability_bindings.capability IS '能力 key。见 ai_config_router.py 中的 KNOWN_CAPABILITIES。';
COMMENT ON COLUMN ai_capability_bindings.priority IS '0 = primary，1/2/3... 依次 fallback。LLMGateway 按顺序重试。';
COMMENT ON COLUMN ai_capability_bindings.params IS '调用参数覆盖。chat: temperature / max_tokens；embedding: dimensions（若 provider 支持 Matryoshka）';

CREATE INDEX IF NOT EXISTS idx_ai_bindings_capability
    ON ai_capability_bindings (capability, priority) WHERE enabled = true;

-- ─────────────────────────────────────────────────────────────
-- system_configs：登记当前 embedding 维度（由应用层 migrate-dimension 接口维护）
-- ─────────────────────────────────────────────────────────────
INSERT INTO system_configs (config_key, config_value, description)
SELECT 'embedding.dimension', '1536',
       '当前 embedding 向量维度；由 admin AI 配置的 embedding 能力绑定自动探测与迁移'
WHERE NOT EXISTS (
    SELECT 1 FROM system_configs WHERE config_key = 'embedding.dimension'
);

COMMIT;
