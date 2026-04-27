"""
apps/api/core/llm_gateway.py
LLM 统一网关 V2 — DB 驱动的能力路由 + 多 provider fallback

核心变更（V2）：
  - MODEL_ROUTES 硬编码 → 运行时从 ai_capability_bindings 加载
  - 每个 capability 支持 N 级 priority fallback（主 → 备1 → 备2 …）
  - 每个 provider 独立 AsyncOpenAI client（独立 base_url / api_key）
  - 配置缓存 TTL 60 秒；admin 保存后通过 reload() 主动失效（API 进程即时生效，
    Celery worker 最多 60 秒后感知）
  - 未绑定能力时回退到 CONFIG.llm.*（LEGACY_ROUTES），保证升级零停机

兼容性：
  teach / generate / embed / embed_single / evaluate_coherence 签名不变。
  旧的 model_route 字符串（如 "knowledge_extraction"）现在即 capability key，无需改调用方。

保留历史修复：
  FIX-F: AsyncOpenAI client timeout=30s
  FIX-G: embed 调用失败时返回空列表，不挂死任务
  FIX-H: _paragraph_coherence 对空向量保护
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import structlog
from openai import AsyncOpenAI, APIError

from apps.api.core.config import CONFIG
from apps.api.core.crypto import decrypt
from packages.shared_schemas.enums import CERTAINTY_SCORE_MAP, CertaintyLevel, GapType

logger = structlog.get_logger(__name__)

# ── 结构化输出规格 ─────────────────────────────────────────────────────────
TEACHING_STRUCTURED_PROMPT_SUFFIX = """

请严格以如下 JSON 格式输出，不要输出任何其他内容（不要 markdown 代码块）：
{
  "response": "你的教学回答（支持 markdown 格式）",
  "certainty_level": "high|medium|low",
  "gap_types": ["mechanism"],
  "error_pattern": "一句话描述用户的错误推理，如无则为 null",
  "proactive_question": "苏格拉底式追问，引导深化理解；无需追问时为 null"
}
certainty_level 含义：
  high   = 对用户理解核心概念有较高把握
  medium = 用户问题模糊，理解情况不确定
  low    = 用户存在明显误解，需要重新解释
gap_types 可选值：definition / mechanism / flow / distinction / application / causal
proactive_question：certainty_level 为 low/medium 时生成开放式追问，high 且无 gap 时为 null
"""

# 配置缓存 TTL（秒）。admin 改完配置 reload() 是主动失效，这里是兜底防止进程间漂移。
_CACHE_TTL_SECONDS = 60


class TeachResponse:
    """LLM 教学响应的结构化载体。"""

    def __init__(
        self,
        response_text: str,
        certainty_level: str,
        gap_types: list[str],
        error_pattern: str | None,
        proactive_question: str | None = None,
    ) -> None:
        self.response_text      = response_text
        self.certainty_level    = certainty_level
        self.gap_types          = [GapType(g) for g in gap_types if g in GapType._value2member_map_]
        self.error_pattern      = error_pattern
        self.proactive_question = proactive_question


def normalize_rrf_score(raw_rrf: float, num_paths: int = 2, k: int = 60) -> float:
    """将 RRF 原始分归一化到 [0, 1]。"""
    if raw_rrf <= 0:
        return 0.0
    max_possible = num_paths / (k + 1)
    return min(1.0, raw_rrf / max_possible)


class _Binding:
    """运行时 capability 绑定（内存态）。"""
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


class LLMGateway:
    """
    V2：DB 驱动的能力路由网关。

    使用示例（调用方无需改动，model_route 原样传旧的字符串即可）：
        gw = get_llm_gateway()
        resp = await gw.generate("请解释...", model_route="knowledge_extraction")
        vecs = await gw.embed(["text1", "text2"])
    """

    # ── Legacy fallback：DB 未配置对应能力时，chat 类能力回退到旧的 CONFIG.llm ──
    # 这样升级到 V2 后，即便 admin 还没在 UI 里绑定，现有 chat 功能不会挂。
    LEGACY_ROUTES: dict[str, str] = {
        "teaching_chat_simple":  "deepseek-chat",
        "teaching_chat_complex": "deepseek-chat",
        "knowledge_extraction":  "deepseek-chat",
        "quality_evaluation":    "deepseek-chat",
        "quiz_generation":       "deepseek-chat",
        "coherence_eval":        "deepseek-chat",
    }
    # 保持对外属性名不变，外部代码若有 `LLMGateway.MODEL_ROUTES` 引用不会挂
    MODEL_ROUTES = LEGACY_ROUTES

    def __init__(self) -> None:
        self._clients: dict[str, AsyncOpenAI] = {}           # provider_id → client
        self._routes: dict[str, list[_Binding]] = {}         # capability → sorted bindings
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()
        self._legacy_client: AsyncOpenAI | None = None

    # ── 配置加载 ─────────────────────────────────────────────────────
    async def _ensure_loaded(self) -> None:
        if self._routes and (time.monotonic() - self._loaded_at) < _CACHE_TTL_SECONDS:
            return
        async with self._lock:
            if self._routes and (time.monotonic() - self._loaded_at) < _CACHE_TTL_SECONDS:
                return
            await self._load_from_db()

    async def reload(self) -> None:
        """admin 保存配置后主动调用，立即刷新当前进程缓存。"""
        async with self._lock:
            await self._load_from_db()

    async def _load_from_db(self) -> None:
        """从 ai_capability_bindings + ai_providers 加载路由表。"""
        from sqlalchemy import text
        from apps.api.core.db import async_session_factory

        routes: dict[str, list[_Binding]] = {}
        try:
            async with async_session_factory() as session:
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
                        base_url    = row.base_url,
                        api_key     = api_key,
                        kind        = row.kind,
                        model_name  = row.model_name,
                        params      = row.params or {},
                        priority    = row.priority,
                    )
                    routes.setdefault(row.capability, []).append(binding)

            # 旧 client 可能用旧 api_key，绑定变化后需要丢弃重建
            self._clients.clear()
            self._routes = routes
            self._loaded_at = time.monotonic()
            logger.info("LLMGateway routes loaded",
                        capabilities=list(routes.keys()),
                        total_bindings=sum(len(v) for v in routes.values()))
        except Exception as exc:
            logger.warning("LLMGateway load_from_db failed, will use legacy fallback",
                           error=str(exc))
            # 不清空已有缓存，防止暂时性 DB 问题导致所有能力失效
            self._loaded_at = time.monotonic()

    def _get_client(self, binding: _Binding) -> AsyncOpenAI:
        """按 provider_id 复用 AsyncOpenAI client。"""
        if binding.provider_id not in self._clients:
            self._clients[binding.provider_id] = AsyncOpenAI(
                api_key  = binding.api_key or "not-set",
                base_url = binding.base_url,
                timeout  = 30.0,
            )
        return self._clients[binding.provider_id]

    def _get_legacy_client(self) -> AsyncOpenAI:
        """LEGACY fallback：未绑定时用 CONFIG.llm。"""
        if self._legacy_client is None:
            self._legacy_client = AsyncOpenAI(
                api_key  = CONFIG.llm.openai_api_key,
                base_url = CONFIG.llm.openai_base_url,
                timeout  = 30.0,
            )
        return self._legacy_client

    async def _resolve(self, capability: str) -> list[tuple[AsyncOpenAI, str, dict]]:
        """
        返回 [(client, model_name, params), ...]，按 priority 从主到备。
        - DB 有绑定：返回所有启用的 bindings
        - DB 无绑定但属于 LEGACY_ROUTES：返回 CONFIG.llm 的 legacy client
        - 其他：返回空列表
        """
        await self._ensure_loaded()
        if capability in self._routes and self._routes[capability]:
            return [(self._get_client(b), b.model_name, b.params) for b in self._routes[capability]]

        if capability in self.LEGACY_ROUTES:
            legacy_model = self.LEGACY_ROUTES[capability]
            logger.debug("LLMGateway legacy fallback",
                         capability=capability, model=legacy_model)
            return [(self._get_legacy_client(), legacy_model, {})]

        return []

    # ── 对外业务方法 ─────────────────────────────────────────────────
    async def teach(
        self,
        model_route: str,
        system_prompt: str,
        messages: list[dict],
        user_message: str,
        knowledge_context: list[Any],
    ) -> TeachResponse:
        """教学对话调用，返回结构化 TeachResponse。多 provider fallback。"""
        context_text = "\n".join(
            f"- {item.canonical_name}: {getattr(item, 'short_definition', '')}"
            for item in knowledge_context[:5]
        ) if knowledge_context else "（无相关知识点）"

        full_system = (
            system_prompt
            + f"\n\n相关知识点：\n{context_text}"
            + TEACHING_STRUCTURED_PROMPT_SUFFIX
        )
        msgs = [{"role": "system", "content": full_system}]
        msgs.extend(messages[-6:])
        msgs.append({"role": "user", "content": user_message})

        resolved = await self._resolve(model_route)
        if not resolved:
            logger.error("No providers configured for teach", capability=model_route)
            return self._template_response(knowledge_context)

        last_error: Exception | None = None
        for client, model, params in resolved:
            try:
                return await self._call_teach(client, model, msgs, params)
            except APIError as exc:
                last_error = exc
                logger.warning("teach provider failed, trying next",
                               model=model, error=str(exc))
                continue
        logger.error("All providers failed for teach",
                     capability=model_route, error=str(last_error))
        return self._template_response(knowledge_context)

    async def _call_teach(self, client, model: str, msgs: list[dict], params: dict) -> TeachResponse:
        resp = await client.chat.completions.create(
            model=model,
            messages=msgs,
            temperature=params.get("temperature", 0.3),
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip())
        data = json.loads(raw)
        return TeachResponse(
            response_text      = data.get("response", ""),
            certainty_level    = data.get("certainty_level", "medium"),
            gap_types          = data.get("gap_types", []),
            error_pattern      = data.get("error_pattern"),
            proactive_question = data.get("proactive_question"),
        )

    def _template_response(self, knowledge_context: list[Any]) -> TeachResponse:
        """最终降级：基于检索结果构造模板回答。"""
        top = knowledge_context[0] if knowledge_context else None
        txt = (
            f"（当前 AI 服务暂时不可用）根据知识库：{top.short_definition}"
            if top else "（当前 AI 服务暂时不可用）暂无相关内容，请稍后再试。"
        )
        return TeachResponse(
            response_text   = txt,
            certainty_level = CertaintyLevel.LOW,
            gap_types       = [],
            error_pattern   = None,
        )

    async def generate(self, prompt: str, model_route: str = "knowledge_extraction") -> str:
        """通用文本生成，多 provider fallback。"""
        resolved = await self._resolve(model_route)
        if not resolved:
            logger.error("No providers configured for generate", capability=model_route)
            raise RuntimeError(f"No providers available for capability '{model_route}'")

        last_error: Exception | None = None
        for client, model, params in resolved:
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=params.get("temperature", 0.2),
                )
                return resp.choices[0].message.content or ""
            except APIError as exc:
                last_error = exc
                logger.warning("generate provider failed, trying next",
                               model=model, error=str(exc))
                continue
        logger.error("All providers failed for generate",
                     capability=model_route, error=str(last_error))
        raise last_error or RuntimeError(f"No providers available for capability '{model_route}'")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        批量文本向量化。多 provider fallback。
        FIX-G：未配置 embedding 能力时返回空列表（每个文本对应 []），
               调用方需处理空向量场景。
        """
        if not texts:
            return []

        resolved = await self._resolve("embedding")
        if not resolved:
            logger.warning("embedding capability not configured, returning empty vectors",
                           text_count=len(texts))
            return [[] for _ in texts]

        last_error: Exception | None = None
        for client, model, params in resolved:
            try:
                kwargs: dict = {"model": model, "input": texts}
                # 某些 provider（如 OpenAI text-embedding-3-*）支持 Matryoshka 维度裁剪
                if "dimensions" in params:
                    kwargs["dimensions"] = params["dimensions"]
                resp = await client.embeddings.create(**kwargs)
                return [item.embedding for item in resp.data]
            except Exception as exc:
                last_error = exc
                logger.warning("embedding provider failed, trying next",
                               model=model, error=str(exc))
                continue

        logger.error("All embedding providers failed",
                     text_count=len(texts), error=str(last_error))
        return [[] for _ in texts]

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed([text])
        return results[0] if results else []

    async def evaluate_coherence(self, content: str) -> float:
        """LLM 辅助连贯性评分（仅作参考，不用于门禁判断）。返回 1-5 分，失败默认 3.0。"""
        prompt = (
            "请评估以下教学文本的逻辑连贯性，给出 1-5 的整数评分。"
            "1=完全不连贯，5=逻辑非常清晰。只输出数字，不要其他内容。\n\n"
            f"{content[:2000]}"
        )
        try:
            result = await self.generate(prompt, model_route="coherence_eval")
            return float(result.strip())
        except Exception:
            return 3.0


# ── 全局单例 ──────────────────────────────────────────────────────────────
_llm_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    global _llm_gateway
    if _llm_gateway is None:
        _llm_gateway = LLMGateway()
    return _llm_gateway
