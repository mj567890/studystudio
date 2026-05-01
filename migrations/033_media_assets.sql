-- migrations/033_media_assets.sql
-- Phase 0：图表/图片资产表 — Media Gateway 渲染输出存储
-- 2026-04-30

BEGIN;

-- ─────────────────────────────────────────────────────────────
-- 扩展 ai_providers.kind 约束：支持 image_api / image_local
-- ─────────────────────────────────────────────────────────────
ALTER TABLE ai_providers DROP CONSTRAINT IF EXISTS ai_providers_kind_check;
ALTER TABLE ai_providers ADD CONSTRAINT ai_providers_kind_check CHECK (kind IN
    ('openai_compatible','anthropic','gemini','ollama','azure_openai','image_api','image_local'));

-- ─────────────────────────────────────────────────────────────
-- media_assets：LLM 生成的图表 → MediaGateway 渲染 → MinIO 存储
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS media_assets (
    asset_id      uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    chapter_id    uuid NOT NULL REFERENCES skill_chapters(chapter_id) ON DELETE CASCADE,
    diagram_spec  text NOT NULL,           -- LLM 输出的原始图表描述/Mermaid 代码
    storage_key   text,                    -- MinIO key (eg. diagrams/{chapter_id}/{sha256[:16]}.svg)
    content_type  varchar(50),             -- image/svg+xml, image/png
    provider_kind varchar(30),             -- 由哪个 provider 渲染 (kroki/openai_compatible/...)
    width         int,                     -- 渲染后宽度 (px)
    height        int,                     -- 渲染后高度 (px)
    sort_order    int NOT NULL DEFAULT 0,  -- 图表在章节中的出现顺序
    created_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  media_assets IS '章节图表渲染资产。LLM 输出 diagram_spec → MediaGateway 渲染 → MinIO 存储 URL';
COMMENT ON COLUMN media_assets.diagram_spec IS 'LLM 输出的原始 Mermaid 代码或图片 prompt，可复用重新渲染';
COMMENT ON COLUMN media_assets.storage_key IS 'MinIO 对象 key；NULL 表示渲染失败或未渲染';
COMMENT ON COLUMN media_assets.provider_kind IS '实际使用的 provider kind，用于追溯渲染来源';

CREATE INDEX IF NOT EXISTS idx_media_assets_chapter
    ON media_assets (chapter_id, sort_order);

COMMIT;
