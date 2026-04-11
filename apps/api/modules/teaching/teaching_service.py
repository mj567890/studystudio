"""
apps/api/modules/teaching/teaching_service.py
Block E：交互教学与检索模块

包含：
- RetrievalFusionService：BM25 + 向量检索 + RRF 融合
- TeachingChatService：教学对话（D3+R1 BackgroundTasks + 独立 session）
- DiagnosisWriteService：乐观锁诊断写入
"""
import json
import math
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import BackgroundTasks, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db, get_independent_db
from apps.api.core.events import get_event_bus
from apps.api.core.llm_gateway import (
    LLMGateway,
    TeachResponse,
    get_llm_gateway,
    normalize_rrf_score,
)
from packages.shared_schemas.enums import CERTAINTY_SCORE_MAP, GapType

logger = structlog.get_logger(__name__)

TEACHING_SYSTEM_PROMPT = """你是一位专业的自适应学习辅导教师。
学习者当前知识掌握情况摘要：{mastery_summary}
当前学习主题：{topic}

请根据学习者的掌握情况，用清晰、易懂的语言回答问题，必要时举例说明。
如发现学习者存在知识误解，请温和地纠正并解释正确概念。
"""


# ════════════════════════════════════════════════════════════════
# 复杂度分类器
# ════════════════════════════════════════════════════════════════
SIMPLE_HOW_PATTERNS = [
    "如何安装", "怎么安装", "如何配置", "如何启动", "如何运行",
    "怎么用", "怎么打开", "如何下载",
]


def classify_query_complexity(message: str, gap_types: list = None) -> str:
    """
    V2.6：移除 no_prior_context 信号，细化 deep_inquiry 排除操作类询问词。
    满足 2 项及以上信号 → complex，否则 → simple。
    """
    msg_lower = message.lower()

    # 操作类询问词检查（负向过滤）
    is_simple_how = any(pattern in message for pattern in SIMPLE_HOW_PATTERNS)

    signals = {
        "long_message":  len(message) > 200,
        "multi_question": (message.count("？") + message.count("?")) > 1,
        "deep_inquiry":   (
            any(w in message for w in ["为什么", "原理", "机制", "区别", "对比", "如何理解", "本质"])
            and not is_simple_how
        ),
        "gap_rich": len(gap_types or []) >= 2,
    }

    return "complex" if sum(signals.values()) >= 2 else "simple"


# ════════════════════════════════════════════════════════════════
# 检索融合服务
# ════════════════════════════════════════════════════════════════
class RankedKnowledgeItem:
    def __init__(self, entity_id: str, rrf_score: float, canonical_name: str,
                 short_definition: str) -> None:
        self.entity_id       = entity_id
        self.rrf_score       = rrf_score
        self.canonical_name  = canonical_name
        self.short_definition = short_definition


class RetrievalFusionService:
    """BM25 + 向量检索 + RRF 融合检索。"""

    K    = 60    # RRF 参数
    TOP_K = 5

    def __init__(self, db: AsyncSession) -> None:
        self.db  = db
        self.llm = get_llm_gateway()

    async def retrieve(
        self, query: str, user_id: str, topic_key: str,
        space_id:   str | None = None,
        domain_tag: str | None = None,
        chapter_id: str | None = None,
    ) -> list[RankedKnowledgeItem]:
        """
        两路召回 + RRF 融合。
        返回最相关的 TOP_K 个知识点。
        space_id / domain_tag / chapter_id 不为 None 时进行作用域过滤。
        """
        # 并行执行两路召回
        bm25_results   = await self._bm25_search(query, space_id, domain_tag, chapter_id)
        vector_results = await self._vector_search(query, space_id, domain_tag, chapter_id)

        # RRF 融合
        scores: dict[str, float] = {}
        entity_info: dict[str, dict] = {}

        for rank, item in enumerate(bm25_results):
            eid = item["entity_id"]
            scores[eid] = scores.get(eid, 0) + 1.0 / (self.K + rank + 1)
            entity_info[eid] = item

        for rank, item in enumerate(vector_results):
            eid = item["entity_id"]
            scores[eid] = scores.get(eid, 0) + 1.0 / (self.K + rank + 1)
            entity_info.setdefault(eid, item)

        sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)
        return [
            RankedKnowledgeItem(
                entity_id       = eid,
                rrf_score       = scores[eid],
                canonical_name  = entity_info[eid]["canonical_name"],
                short_definition = entity_info[eid].get("short_definition", ""),
            )
            for eid in sorted_ids[:self.TOP_K]
        ]

    async def _bm25_search(
        self, query: str,
        space_id:   str | None = None,
        domain_tag: str | None = None,
        chapter_id: str | None = None,
    ) -> list[dict]:
        chapter_join = (
            "JOIN chapter_entity_links cel "
            "ON cel.entity_id = ke.entity_id "
            "AND cel.chapter_id = CAST(:chapter_id AS uuid)"
            if chapter_id else ""
        )
        sql = f"""
            SELECT ke.entity_id::text, ke.canonical_name, ke.short_definition,
                   ts_rank(
                     to_tsvector('simple', COALESCE(ke.canonical_name,'') || ' ' || COALESCE(ke.short_definition,'')),
                     plainto_tsquery('simple', :query)
                   ) AS score
            FROM knowledge_entities ke
            {chapter_join}
            WHERE ke.review_status = 'approved'
              AND (CAST(:space_id AS text) IS NULL OR ke.space_id = CAST(:space_id AS uuid) OR ke.space_type = 'global')
              AND (CAST(:domain_tag AS text) IS NULL OR ke.domain_tag = :domain_tag)
              AND to_tsvector('simple', COALESCE(ke.canonical_name,'') || ' ' || COALESCE(ke.short_definition,''))
                  @@ plainto_tsquery('simple', :query)
            ORDER BY score DESC
            LIMIT 30
        """
        result = await self.db.execute(
            text(sql),
            {"query": query, "space_id": space_id,
             "domain_tag": domain_tag, "chapter_id": chapter_id}
        )
        return [dict(r._mapping) for r in result.fetchall()]

    async def _vector_search(
        self, query: str,
        space_id:   str | None = None,
        domain_tag: str | None = None,
        chapter_id: str | None = None,
    ) -> list[dict]:
        query_emb = await self.llm.embed_single(query)
        if not query_emb or len(query_emb) == 0:
            return []
        chapter_join = (
            "JOIN chapter_entity_links cel "
            "ON cel.entity_id = ke.entity_id "
            "AND cel.chapter_id = CAST(:chapter_id AS uuid)"
            if chapter_id else ""
        )
        sql = f"""
            SELECT ke.entity_id::text, ke.canonical_name, ke.short_definition,
                   1 - (ke.embedding <=> CAST(:emb AS vector)) AS similarity
            FROM knowledge_entities ke
            {chapter_join}
            WHERE ke.review_status = 'approved'
              AND ke.embedding IS NOT NULL
              AND (CAST(:space_id AS text) IS NULL OR ke.space_id = CAST(:space_id AS uuid) OR ke.space_type = 'global')
              AND (CAST(:domain_tag AS text) IS NULL OR ke.domain_tag = :domain_tag)
            ORDER BY ke.embedding <=> CAST(:emb AS vector)
            LIMIT 30
        """
        result = await self.db.execute(
            text(sql),
            {"emb": str(query_emb), "space_id": space_id,
             "domain_tag": domain_tag, "chapter_id": chapter_id}
        )
        return [dict(r._mapping) for r in result.fetchall()]


# ════════════════════════════════════════════════════════════════
# 诊断写入服务（后台任务调用）
# ════════════════════════════════════════════════════════════════
class DiagnosisUpdate:
    def __init__(
        self,
        suspected_gap_types: list[GapType],
        updated_entities:    list[str],
        confidence:          float,
        error_pattern:       str | None,
    ) -> None:
        self.suspected_gap_types = suspected_gap_types
        self.updated_entities    = updated_entities
        self.confidence          = confidence
        self.error_pattern       = error_pattern


class DiagnosisWriteService:
    """乐观锁诊断写入，支持并发合并。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def update_with_lock(
        self, user_id: str, diagnosis: DiagnosisUpdate, version: int
    ) -> None:
        """
        使用乐观锁写入诊断结果。
        version 冲突时合并：差值 < 0.1 取并集，否则取高 confidence 方。
        """
        result = await self.db.execute(
            text("SELECT version, mastery_summary FROM learner_profiles WHERE user_id = :user_id"),
            {"user_id": user_id}
        )
        row = result.fetchone()
        if not row:
            return

        current_version = row.version

        if current_version == version:
            # 版本一致，直接写入
            await self._apply_diagnosis(user_id, diagnosis, current_version)
        else:
            # 版本冲突，合并诊断
            prev_data = row.mastery_summary or {}
            prev_confidence = prev_data.get("last_confidence", 0.5)
            prev_gap_types  = [GapType(g) for g in prev_data.get("last_gap_types", [])
                               if g in GapType._value2member_map_]

            if abs(diagnosis.confidence - prev_confidence) < 0.1:
                # 置信度差异小，取并集
                merged_gaps = list(set(diagnosis.suspected_gap_types) | set(prev_gap_types))
                merged_confidence = max(diagnosis.confidence, prev_confidence)
            else:
                # 取高置信度一方
                if diagnosis.confidence > prev_confidence:
                    merged_gaps       = diagnosis.suspected_gap_types
                    merged_confidence = diagnosis.confidence
                else:
                    merged_gaps       = prev_gap_types
                    merged_confidence = prev_confidence

            merged = DiagnosisUpdate(
                suspected_gap_types = merged_gaps,
                updated_entities    = list(set(diagnosis.updated_entities)),
                confidence          = merged_confidence,
                error_pattern       = diagnosis.error_pattern,
            )
            await self._apply_diagnosis(user_id, merged, current_version)

        event_bus = get_event_bus()
        await event_bus.publish("diagnosis_updated", {
            "user_id":             user_id,
            "suspected_gap_types": [g.value for g in diagnosis.suspected_gap_types],
            "updated_entities":    diagnosis.updated_entities,
            "confidence":          diagnosis.confidence,
        })

    async def _apply_diagnosis(
        self, user_id: str, diagnosis: DiagnosisUpdate, current_version: int
    ) -> None:
        summary_update = {
            "last_gap_types":   [g.value for g in diagnosis.suspected_gap_types],
            "last_confidence":  diagnosis.confidence,
            "last_error_pattern": diagnosis.error_pattern,
            "updated_at":       datetime.now(timezone.utc).isoformat(),
        }
        await self.db.execute(
            text("""
                UPDATE learner_profiles
                SET mastery_summary = mastery_summary || CAST(:update AS jsonb),
                    version = version + 1,
                    updated_at = NOW()
                WHERE user_id = :user_id AND version = :version
            """),
            {
                "user_id": user_id,
                "update":  json.dumps(summary_update),
                "version": current_version,
            }
        )
        await self.db.commit()


# ════════════════════════════════════════════════════════════════
# 教学对话服务
# ════════════════════════════════════════════════════════════════
class TeachingChatService:
    """
    教学对话主服务。
    D3+R1（V2.6）：chat_and_prepare 不内部触发诊断写入，
    返回三元组供路由层用 BackgroundTasks 处理。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db  = db
        self.llm = get_llm_gateway()

    async def chat_and_prepare(
        self,
        conversation_id: str,
        user_message:    str,
        topic_key:       str,
        user_id:         str,
        space_id:        str | None = None,
        domain_tag:      str | None = None,
        chapter_id:      str | None = None,
    ) -> tuple[dict, DiagnosisUpdate, int]:
        """
        教学对话核心逻辑。
        返回 (response_dict, diagnosis, profile_version)。
        """
        # 获取用户画像（含版本号，用于乐观锁）
        profile_result = await self.db.execute(
            text("SELECT mastery_summary, version FROM learner_profiles WHERE user_id = :user_id"),
            {"user_id": user_id}
        )
        profile_row  = profile_result.fetchone()
        mastery_summary = (profile_row.mastery_summary or {}) if profile_row else {}
        profile_version = profile_row.version if profile_row else 0

        # 获取对话历史（最近 6 轮）
        history_result = await self.db.execute(
            text("""
                SELECT role, content, gap_type, error_pattern
                FROM conversation_turns
                WHERE conversation_id = :conv_id
                ORDER BY created_at DESC
                LIMIT 12
            """),
            {"conv_id": conversation_id}
        )
        turns   = list(reversed(history_result.fetchall()))
        messages = [{"role": t.role, "content": t.content} for t in turns[-6:]]

        # 从历史中提取 gap_types（用于复杂度分类）
        recent_gap_types = [
            t.gap_type for t in turns[-3:] if t.gap_type
        ]

        # 复杂度分类路由
        complexity  = classify_query_complexity(user_message, recent_gap_types)
        model_route = "teaching_chat_complex" if complexity == "complex" \
                      else "teaching_chat_simple"

        # 检索相关知识点
        retrieval_svc = RetrievalFusionService(self.db)
        retrieved = await retrieval_svc.retrieve(
            user_message, user_id, topic_key,
            space_id=space_id, domain_tag=domain_tag, chapter_id=chapter_id,
        )

        # LLM 教学调用（结构化输出，三级降级）
        system_prompt = TEACHING_SYSTEM_PROMPT.format(
            mastery_summary=json.dumps(mastery_summary, ensure_ascii=False)[:500],
            topic=topic_key,
        )
        teach_resp: TeachResponse = await self.llm.teach(
            model_route      = model_route,
            system_prompt    = system_prompt,
            messages         = messages,
            user_message     = user_message,
            knowledge_context = retrieved,
        )

        # 计算置信度（RRF 归一化后参与计算）
        raw_rrf    = retrieved[0].rrf_score if retrieved else 0.0
        norm_score = normalize_rrf_score(raw_rrf)
        llm_cert   = CERTAINTY_SCORE_MAP.get(teach_resp.certainty_level, 0.6)
        confidence = round(0.6 * llm_cert + 0.4 * norm_score, 3)

        diagnosis = DiagnosisUpdate(
            suspected_gap_types = teach_resp.gap_types,
            updated_entities    = [r.entity_id for r in retrieved[:3]],
            confidence          = confidence,
            error_pattern       = teach_resp.error_pattern,
        )

        # 保存对话轮次
        turn_id = str(uuid.uuid4())
        await self.db.execute(
            text("""
                INSERT INTO conversation_turns
                  (turn_id, conversation_id, role, content)
                VALUES (:tid, :cid, 'user', :content)
            """),
            {"tid": str(uuid.uuid4()), "cid": conversation_id, "content": user_message}
        )
        await self.db.execute(
            text("""
                INSERT INTO conversation_turns
                  (turn_id, conversation_id, role, content, gap_type, error_pattern, cited_entity_ids)
                VALUES (:tid, :cid, 'assistant', :content, :gap_type, :error_pattern, CAST(:cited AS jsonb))
            """),
            {
                "tid":           turn_id,
                "cid":           conversation_id,
                "content":       teach_resp.response_text,
                "gap_type":      teach_resp.gap_types[0].value if teach_resp.gap_types else None,
                "error_pattern": teach_resp.error_pattern,
                "cited":         json.dumps([r.entity_id for r in retrieved[:3]]),
            }
        )

        # 更新对话轮次计数
        await self.db.execute(
            text("""
                UPDATE conversations SET turn_count = turn_count + 1, updated_at = NOW()
                WHERE conversation_id = :cid
            """),
            {"cid": conversation_id}
        )
        await self.db.commit()

        response = {
            "conversation_id":   conversation_id,
            "turn_id":           turn_id,
            "assistant_message": teach_resp.response_text,
            "cited_entity_ids":  [r.entity_id for r in retrieved[:3]],
            "suggested_next_steps": [
                {"type": "entity", "ref_id": r.entity_id, "title": r.canonical_name}
                for r in retrieved[1:3]
            ],
            "proactive_question": teach_resp.proactive_question,
            "diagnosis_update": {
                "suspected_gap_types": [g.value for g in teach_resp.gap_types],
                "updated_entities":    [r.entity_id for r in retrieved[:3]],
                "confidence":          confidence,
                "error_pattern":       teach_resp.error_pattern,
            },
        }

        return response, diagnosis, profile_version


# ════════════════════════════════════════════════════════════════
# 后台诊断写入任务（D3+R1：使用独立 session）
# ════════════════════════════════════════════════════════════════
async def _run_diagnosis_update(
    user_id:   str,
    diagnosis: DiagnosisUpdate,
    version:   int,
) -> None:
    """
    D3+R1（V2.6）：后台任务使用独立 session，不依赖请求生命周期。
    FastAPI 在响应发送后安全执行。
    """
    async with get_independent_db() as session:
        service = DiagnosisWriteService(session)
        await service.update_with_lock(user_id, diagnosis, version)
