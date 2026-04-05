"""
apps/api/core/llm_gateway.py
LLM 统一网关 —— 支持模型路由、结构化输出、三级降级

V2.6 关键设计：
- teach() 返回 TeachResponse（结构化 JSON），不再依赖关键词匹配
- 三级降级：主模型 → 备用模型 → 检索模板回答
- RRF 分数归一化函数在此定义
"""
import json
import re
from typing import Any

import structlog
from openai import AsyncOpenAI, APIError

from apps.api.core.config import CONFIG
from packages.shared_schemas.enums import CERTAINTY_SCORE_MAP, CertaintyLevel, GapType

logger = structlog.get_logger(__name__)

# ── 结构化输出规格 ─────────────────────────────────────────────────────────
TEACHING_STRUCTURED_PROMPT_SUFFIX = """

请严格以如下 JSON 格式输出，不要输出任何其他内容（不要 markdown 代码块）：
{
  "response": "你的教学回答（支持 markdown 格式）",
  "certainty_level": "high|medium|low",
  "gap_types": ["mechanism"],
  "error_pattern": "一句话描述用户的错误推理，如无则为 null"
}
certainty_level 含义：
  high   = 对用户理解核心概念有较高把握
  medium = 用户问题模糊，理解情况不确定
  low    = 用户存在明显误解，需要重新解释
gap_types 可选值：definition / mechanism / flow / distinction / application / causal
"""


class TeachResponse:
    """LLM 教学响应的结构化载体。"""
    def __init__(
        self,
        response_text: str,
        certainty_level: str,
        gap_types: list[str],
        error_pattern: str | None,
    ) -> None:
        self.response_text    = response_text
        self.certainty_level  = certainty_level
        self.gap_types        = [GapType(g) for g in gap_types if g in GapType._value2member_map_]
        self.error_pattern    = error_pattern


def normalize_rrf_score(raw_rrf: float, num_paths: int = 2, k: int = 60) -> float:
    """
    将 RRF 原始分归一化到 [0, 1]。
    RRF 最大值约为 num_paths / (k + 1)（所有路径均排第一时）。
    归一化后确保置信度公式中检索项具有实际意义。
    """
    if raw_rrf <= 0:
        return 0.0
    max_possible = num_paths / (k + 1)
    return min(1.0, raw_rrf / max_possible)


class LLMGateway:
    """统一 LLM 调用入口，支持模型路由和三级降级。"""

    # 模型路由配置
    MODEL_ROUTES: dict[str, str] = {
        "teaching_chat_simple":  "deepseek-chat",
        "teaching_chat_complex": "deepseek-chat",
        "knowledge_extraction":  "deepseek-chat",
        "quality_evaluation":    "deepseek-chat",
        "quiz_generation":       "deepseek-chat",
        "coherence_eval":        "deepseek-chat",
    }

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=CONFIG.llm.openai_api_key,
            base_url=CONFIG.llm.openai_base_url,
        )

    def _get_model(self, route: str) -> str:
        return self.MODEL_ROUTES.get(route, CONFIG.llm.default_model)

    async def teach(
        self,
        model_route: str,
        system_prompt: str,
        messages: list[dict],
        user_message: str,
        knowledge_context: list[Any],
    ) -> TeachResponse:
        """
        教学对话调用，返回结构化 TeachResponse。
        三级降级：主模型 → 备用模型(gpt-4o-mini) → 检索模板回答
        """
        # 构建知识上下文摘要
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
        msgs.extend(messages[-6:])   # 最近 6 轮
        msgs.append({"role": "user", "content": user_message})

        try:
            return await self._call_teach(self._get_model(model_route), msgs)
        except APIError as e:
            logger.warning("Primary model failed, trying fallback", error=str(e))
            try:
                return await self._call_teach("deepseek-chat", msgs)
            except APIError as e2:
                logger.error("Fallback model failed, using template", error=str(e2))
                return self._template_response(knowledge_context)

    async def _call_teach(self, model: str, messages: list[dict]) -> TeachResponse:
        resp = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        # 清理可能的 markdown 代码块包裹
        raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip())
        data = json.loads(raw)
        return TeachResponse(
            response_text=data.get("response", ""),
            certainty_level=data.get("certainty_level", "medium"),
            gap_types=data.get("gap_types", []),
            error_pattern=data.get("error_pattern"),
        )

    def _template_response(self, knowledge_context: list[Any]) -> TeachResponse:
        """最终降级：基于检索结果构造模板回答。"""
        top = knowledge_context[0] if knowledge_context else None
        text = (
            f"（当前 AI 服务暂时不可用）根据知识库：{top.short_definition}"
            if top else "（当前 AI 服务暂时不可用）暂无相关内容，请稍后再试。"
        )
        return TeachResponse(
            response_text=text,
            certainty_level=CertaintyLevel.LOW,
            gap_types=[],
            error_pattern=None,
        )

    async def generate(self, prompt: str, model_route: str = "knowledge_extraction") -> str:
        """通用文本生成（知识抽取、教程内容等使用）。"""
        resp = await self._client.chat.completions.create(
            model=self._get_model(model_route),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化。"""
        resp = await self._client.embeddings.create(
            model=CONFIG.llm.embedding_model,
            input=texts,
        )
        return [item.embedding for item in resp.data]

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed([text])
        return results[0]

    async def evaluate_coherence(self, content: str) -> float:
        """
        LLM 辅助连贯性评分（仅作参考，不用于门禁判断）。
        返回 1-5 分，调用方除以 5.0 归一化。
        """
        prompt = (
            "请评估以下教学文本的逻辑连贯性，给出 1-5 的整数评分。"
            "1=完全不连贯，5=逻辑非常清晰。只输出数字，不要其他内容。\n\n"
            f"{content[:2000]}"
        )
        try:
            result = await self.generate(prompt, model_route="coherence_eval")
            return float(result.strip())
        except (ValueError, APIError):
            return 3.0


# 全局单例
_llm_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    global _llm_gateway
    if _llm_gateway is None:
        _llm_gateway = LLMGateway()
    return _llm_gateway
