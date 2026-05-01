"""
apps/api/core/media_gateway.py
Media Gateway — 图表/图片生成网关

架构：完全复用 LLMGateway 的 DB 驱动能力路由 + 多 provider fallback 模式。

Provider tier:
  Tier 1 (priority=0): Kroki — 文本→图表 (Mermaid/PlantUML), 0 VRAM, 免费
  Tier 2 (priority=1): DALL-E / Seedream — 文本→图片, 0 VRAM, 按量付费
  Tier 3 (priority=2): ComfyUI / FLUX — 文本→图片, 12-384GB VRAM, 免费

能力 key:
  - diagram_generation: 文本→图表 (Kroki 等, kind=image_local)
  - image_generation:   文本→图片 (DALL-E/ComfyUI, kind=image_api/image_local)

使用示例:
    gw = get_media_gateway()
    result = await gw.render_diagram(chapter_id, spec, format="mermaid")
    if result:
        print(result.storage_key, result.presigned_url)
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from openai import AsyncOpenAI, APIError, APIConnectionError, APITimeoutError

from apps.api.core.config import CONFIG

logger = structlog.get_logger(__name__)

_CACHE_TTL_SECONDS = 60


@dataclass
class MediaAssetResult:
    """渲染结果。"""
    storage_key: str
    presigned_url: str
    content_type: str
    provider_kind: str
    width: int | None = None
    height: int | None = None


class _Binding:
    """运行时 capability 绑定（内存态）— 与 LLMGateway._Binding 相同结构。"""
    __slots__ = ("provider_id", "base_url", "api_key", "kind",
                 "model_name", "params", "priority")

    def __init__(self, provider_id, base_url, api_key, kind, model_name, params, priority):
        self.provider_id = provider_id
        self.base_url    = base_url
        self.api_key     = api_key
        self.kind        = kind
        self.model_name  = model_name
        self.params      = params or {}
        self.priority    = priority


class MediaGateway:
    """
    图表/图片生成网关。

    DB 驱动路由：ai_capability_bindings (capability + priority) → ai_providers (base_url + kind)。
    按 priority 排序逐个尝试，失败自动 fallback 到下一个 provider。
    """

    DIAGRAM_CAPABILITY = "diagram_generation"
    IMAGE_CAPABILITY   = "image_generation"

    def __init__(self) -> None:
        self._routes: dict[str, list[_Binding]] = {}
        self._loaded_at: float = 0.0
        self._lock = None
        self._lock_loop = None

    # ── 配置加载（复用 LLMGateway 模式）────────────────────────────────

    def _get_lock(self):
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
            if hasattr(self, "_routes"):
                pass  # routes 持留，Celery prefork 场景不清空
        return self._lock

    async def _ensure_loaded(self) -> None:
        if self._routes and (time.monotonic() - self._loaded_at) < _CACHE_TTL_SECONDS:
            return
        async with self._get_lock():
            if self._routes and (time.monotonic() - self._loaded_at) < _CACHE_TTL_SECONDS:
                return
            await self._load_from_db()

    async def reload(self) -> None:
        """Admin 保存配置后主动调用，立即刷新当前进程缓存。"""
        async with self._get_lock():
            await self._load_from_db()

    async def _load_from_db(self) -> None:
        """从 ai_capability_bindings + ai_providers 加载路由表。"""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from apps.api.core.crypto import decrypt

        _tmp_engine = create_async_engine(CONFIG.database.url, pool_pre_ping=True, pool_size=2)
        _tmp_sf = async_sessionmaker(bind=_tmp_engine, class_=AsyncSession, expire_on_commit=False)

        routes: dict[str, list[_Binding]] = {}
        try:
            async with _tmp_sf() as session:
                result = await session.execute(text("""
                    SELECT b.capability,
                           b.model_name,
                           b.priority,
                           b.params,
                           p.provider_id::text AS provider_id,
                           p.base_url,
                           p.api_key_encrypted,
                           p.kind
                    FROM ai_capability_bindings b
                    JOIN ai_providers p ON p.provider_id = b.provider_id
                    WHERE b.enabled = true AND p.enabled = true
                    ORDER BY b.capability, b.priority
                """))
                for row in result.fetchall():
                    api_key = decrypt(row.api_key_encrypted or "")
                    binding = _Binding(
                        provider_id = row.provider_id,
                        base_url    = (row.base_url or "").strip(),
                        api_key     = api_key,
                        kind        = row.kind,
                        model_name  = (row.model_name or "").strip(),
                        params      = row.params or {},
                        priority    = row.priority,
                    )
                    routes.setdefault(row.capability, []).append(binding)

            self._routes = routes
            self._loaded_at = time.monotonic()
            logger.info("MediaGateway routes loaded",
                        capabilities=list(routes.keys()),
                        total_bindings=sum(len(v) for v in routes.values()))
        except Exception as exc:
            logger.warning("MediaGateway load_from_db failed", error=str(exc))
            self._loaded_at = time.monotonic()
        finally:
            await _tmp_engine.dispose()

    async def _resolve(self, capability: str) -> list[_Binding]:
        """返回按 priority 排序的 provider bindings。无绑定返回空列表。"""
        await self._ensure_loaded()
        return self._routes.get(capability, [])

    # ── 对外方法 ─────────────────────────────────────────────────────────

    async def render_diagram(
        self, chapter_id: str, spec: str, format: str = "mermaid"
    ) -> MediaAssetResult | None:
        """
        图表渲染管道：spec → provider → bytes → MinIO → presigned URL。

        - 先查 MinIO 去重缓存（SHA256），命中则直接返回 presigned URL
        - 未命中则调用 diagram_generation capability bindings 逐个渲染
        - 所有 provider 失败时返回 None（课程仍正常生成，仅无图）
        """
        spec_hash = hashlib.sha256(spec.encode()).hexdigest()[:16]
        ext = "svg" if format in ("mermaid", "plantuml", "graphviz", "svgbob") else "png"
        cache_key = f"diagrams/{chapter_id}/{spec_hash}.{ext}"

        # 检查 MinIO 去重缓存
        if CONFIG.media.diagram_cache_enabled:
            try:
                from apps.api.core.storage import get_minio_client
                minio = get_minio_client()
                if await minio.exists(cache_key):
                    url = _public_url(await minio.presign(cache_key, expires=3600))
                    logger.debug("diagram cache hit", key=cache_key)
                    return MediaAssetResult(
                        storage_key=cache_key,
                        presigned_url=url,
                        content_type=f"image/{ext}",
                        provider_kind="cache",
                    )
            except Exception as exc:
                logger.debug("diagram cache check failed, will re-render", error=str(exc))

        # Provider 渲染
        bindings = await self._resolve(self.DIAGRAM_CAPABILITY)
        if not bindings:
            logger.warning("no diagram_generation provider configured, skipping diagram")
            return None

        last_error: Exception | None = None
        for binding in bindings:
            try:
                data: bytes | None = None
                content_type: str = "image/svg+xml"

                if binding.kind in ("image_local", "kroki"):
                    data = await self._render_kroki(binding, spec, format)
                    if format in ("png",):
                        content_type = "image/png"
                elif binding.kind in ("image_api", "openai_compatible"):
                    data = await self._render_dalle(binding, spec)
                    content_type = "image/png"
                else:
                    logger.warning("unsupported provider kind for diagram, skipping",
                                   kind=binding.kind, provider=binding.provider_id)
                    continue

                if data and len(data) > 0:
                    from apps.api.core.storage import get_minio_client
                    minio = get_minio_client()
                    await minio.upload_bytes(cache_key, data, content_type)
                    url = _public_url(await minio.presign(cache_key, expires=3600))

                    logger.info("diagram rendered",
                                provider=binding.provider_id,
                                kind=binding.kind,
                                size_bytes=len(data))
                    return MediaAssetResult(
                        storage_key=cache_key,
                        presigned_url=url,
                        content_type=content_type,
                        provider_kind=binding.kind,
                    )
                else:
                    raise RuntimeError(f"Provider {binding.provider_id} returned empty data")

            except (APIError, APIConnectionError, APITimeoutError, httpx.HTTPError,
                    httpx.TimeoutException, RuntimeError, ConnectionError) as exc:
                last_error = exc
                logger.warning("diagram provider failed, trying next fallback",
                               provider=binding.provider_id,
                               kind=binding.kind,
                               error=str(exc)[:200])
                continue

        if last_error:
            logger.warning("all diagram providers exhausted, chapter will have no diagram",
                           chapter_id=chapter_id,
                           last_error=str(last_error)[:200])
        return None

    async def _render_kroki(self, binding: _Binding, spec: str, format: str = "mermaid") -> bytes:
        """POST {base_url}/{format}/svg → 返回 SVG/PNG 字节。"""
        base = binding.base_url.rstrip("/")
        output_format = binding.params.get("output_format", "svg")
        url = f"{base}/{format}/{output_format}"

        timeout = float(binding.params.get("timeout", CONFIG.media.kroki_timeout))
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, content=spec, headers={"Content-Type": "text/plain"})
            resp.raise_for_status()
            return resp.content

    async def _render_dalle(self, binding: _Binding, prompt: str) -> bytes:
        """OpenAI DALL-E / 兼容 API → 下载生成的 PNG 字节。"""
        client = AsyncOpenAI(
            api_key=binding.api_key or "not-set",
            base_url=binding.base_url,
            timeout=float(binding.params.get("timeout", 120.0)),
        )
        size = binding.params.get("size", "1024x1024")
        quality = binding.params.get("quality", "standard")

        resp = await client.images.generate(
            model=binding.model_name or "dall-e-3",
            prompt=prompt,
            n=1,
            size=size,
            quality=quality,
        )

        image_url = resp.data[0].url
        if not image_url:
            raise RuntimeError("DALL-E returned no image URL")

        async with httpx.AsyncClient(timeout=60.0) as http_client:
            img_resp = await http_client.get(image_url)
            img_resp.raise_for_status()
            return img_resp.content

    async def render_image(self, chapter_id: str, prompt: str) -> MediaAssetResult | None:
        """
        通用图片生成（Tier 2/3）：prompt → image_generation capability → MinIO → presigned URL。
        用于非图表类图片（概念插图、场景图等）。
        """
        spec_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        cache_key = f"diagrams/{chapter_id}/{spec_hash}.png"

        if CONFIG.media.diagram_cache_enabled:
            try:
                from apps.api.core.storage import get_minio_client
                minio = get_minio_client()
                if await minio.exists(cache_key):
                    url = _public_url(await minio.presign(cache_key, expires=3600))
                    return MediaAssetResult(
                        storage_key=cache_key,
                        presigned_url=url,
                        content_type="image/png",
                        provider_kind="cache",
                    )
            except Exception:
                pass

        bindings = await self._resolve(self.IMAGE_CAPABILITY)
        if not bindings:
            logger.warning("no image_generation provider configured, skipping image")
            return None

        last_error: Exception | None = None
        for binding in bindings:
            try:
                data: bytes | None = None
                if binding.kind in ("image_api", "openai_compatible"):
                    data = await self._render_dalle(binding, prompt)
                elif binding.kind == "image_local":
                    data = await self._render_kroki(binding, prompt, format="png")
                else:
                    continue

                if data and len(data) > 0:
                    from apps.api.core.storage import get_minio_client
                    minio = get_minio_client()
                    await minio.upload_bytes(cache_key, data, "image/png")
                    url = _public_url(await minio.presign(cache_key, expires=3600))

                    return MediaAssetResult(
                        storage_key=cache_key,
                        presigned_url=url,
                        content_type="image/png",
                        provider_kind=binding.kind,
                    )

            except Exception as exc:
                last_error = exc
                logger.warning("image provider failed, trying next fallback",
                               provider=binding.provider_id, error=str(exc)[:200])
                continue

        if last_error:
            logger.warning("all image providers exhausted",
                           chapter_id=chapter_id,
                           last_error=str(last_error)[:200])
        return None


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _public_url(internal_url: str) -> str:
    """将 MinIO Docker 内部地址替换为浏览器可达的公共端点。"""
    public_endpoint = os.environ.get("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000")
    return internal_url.replace("http://minio:9000", public_endpoint)


# ── 全局单例 ──────────────────────────────────────────────────────────────
_media_gateway: MediaGateway | None = None


def get_media_gateway() -> MediaGateway:
    global _media_gateway
    if _media_gateway is None:
        _media_gateway = MediaGateway()
    return _media_gateway
