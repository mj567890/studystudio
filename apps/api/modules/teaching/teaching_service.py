"""
apps/api/modules/teaching/teaching_service.py
Block E：交互教学与检索模块

包含：
- RetrievalFusionService：BM25 + 向量检索 + RRF 融合
- TeachingChatService：教学对话（D3+R1 BackgroundTasks + 独立 session）
- DiagnosisWriteService：乐观锁诊断写入
"""
import asyncio
import json
import math
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import BackgroundTasks, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.exc import ProgrammingError
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

## 学习者当前状态
知识掌握摘要：{mastery_summary}
当前学习主题：{topic}

## 自适应教学策略（请严格遵守）
{adaptive_strategy}

## 通用教学原则
- 如发现学习者存在知识误解，温和纠正并解释正确概念
- 优先用具体例子和类比帮助理解
- 回答长度与问题复杂度匹配，不要过度展开
- 保持对话自然，不要像在朗读教材
"""


# ════════════════════════════════════════════════════════════════
# 复杂度分类器
# ════════════════════════════════════════════════════════════════
SIMPLE_HOW_PATTERNS = [
    "如何安装", "怎么安装", "如何配置", "如何启动", "如何运行",
    "怎么用", "怎么打开", "如何下载",
]



def build_adaptive_strategy(mastery_summary: dict, topic: str) -> str:
    """根据学习者掌握情况生成自适应教学策略指令。"""
    if not mastery_summary:
        return (
            "- 学习者为新手，无历史掌握数据\n"
            "- 请从基础概念入手，用简单语言和类比解释\n"
            "- 避免使用专业术语，如必须使用请立即解释\n"
            "- 每次回答聚焦一个核心概念"
        )

    # 统计掌握度分布
    scores = [v for v in mastery_summary.values() if isinstance(v, (int, float))]
    if not scores:
        avg = 0.0
    else:
        avg = sum(scores) / len(scores)

    weak = [k for k, v in mastery_summary.items() if isinstance(v, (int, float)) and v < 0.4]
    medium = [k for k, v in mastery_summary.items() if isinstance(v, (int, float)) and 0.4 <= v < 0.7]
    strong = [k for k, v in mastery_summary.items() if isinstance(v, (int, float)) and v >= 0.7]

    lines = []

    if avg < 0.35:
        lines.append("- 学习者整体掌握度较低，请使用入门级讲解方式")
        lines.append("- 优先解释基础定义，再展开机制和原理")
        lines.append("- 每个回答结尾用一句话总结核心要点")
    elif avg < 0.65:
        lines.append("- 学习者具备一定基础，可以使用中级讲解方式")
        lines.append("- 可以假设学习者了解基本概念，直接深入机制和原理")
        lines.append("- 鼓励学习者自己推理，适当留白引导思考")
    else:
        lines.append("- 学习者掌握度较高，请使用进阶讲解方式")
        lines.append("- 可以直接讨论边界情况、权衡取舍和实际应用")
        lines.append("- 适合进行苏格拉底式深度追问，挑战学习者思维")

    if weak:
        lines.append(f"- 以下知识点掌握薄弱，讲解时需额外强化：{', '.join(weak[:3])}")
    if strong:
        lines.append(f"- 以下知识点已掌握，无需重复解释：{', '.join(strong[:3])}")

    return "\n".join(lines)

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
                 short_definition: str,
                 source_type: str = "entity",
                 page_no: int | None = None,
                 title_path: list[str] | None = None,
                 rerank_score: float | None = None) -> None:
        self.entity_id       = entity_id
        self.rrf_score       = rrf_score
        self.canonical_name  = canonical_name
        self.short_definition = short_definition
        self.source_type     = source_type    # "entity" | "chunk"
        self.page_no         = page_no
        self.title_path      = title_path
        self.rerank_score    = rerank_score   # Phase 5.x: reranker 精排分 (0-1)，未启用时为 None


class RetrievalFusionService:
    """BM25 + 向量检索 + RRF 融合检索（含文档 chunk 通道）。"""

    K              = 60   # RRF 参数
    TOP_K           = 5    # 最终返回数量
    RERANK_INPUT_N  = 20   # 送入 reranker 的候选数（RRF 粗排取 TOP_N）

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
        两路召回（实体 + chunk）+ RRF 融合，含查询改写增强。
        返回最相关的 TOP_K 个知识点/段落。
        """
        # 5.2 查询改写
        rewritten = await self._rewrite_query(query)
        queries = [query] + (rewritten if rewritten else [])
        if rewritten:
            logger.info("query_rewritten_for_retrieval",
                        original=query[:80], rewritten=rewritten)

        # 并行执行实体检索 + chunk 检索
        all_ent_bm25, all_ent_vec, chunk_bm25, chunk_vec = await asyncio.gather(
            asyncio.gather(*[self._bm25_search(q, space_id, domain_tag, chapter_id)
                           for q in queries]),
            asyncio.gather(*[self._vector_search(q, space_id, domain_tag, chapter_id)
                           for q in queries]),
            self._chunk_bm25(query, space_id),
            self._chunk_vector(query, space_id),
        )

        # RRF 融合（实体 + chunk）
        scores: dict[str, float] = {}
        info: dict[str, dict] = {}

        for bm25_results in all_ent_bm25:
            for rank, item in enumerate(bm25_results):
                eid = item["entity_id"]
                scores[eid] = scores.get(eid, 0) + 1.0 / (self.K + rank + 1)
                info.setdefault(eid, item)

        for vector_results in all_ent_vec:
            for rank, item in enumerate(vector_results):
                eid = item["entity_id"]
                scores[eid] = scores.get(eid, 0) + 1.0 / (self.K + rank + 1)
                info.setdefault(eid, item)

        # 6.2: chunk 结果融入 RRF
        for rank, item in enumerate(chunk_bm25):
            cid = f"chunk:{item['chunk_id']}"
            scores[cid] = scores.get(cid, 0) + 1.0 / (self.K + rank + 1)
            info.setdefault(cid, {"_type": "chunk", **item})

        for rank, item in enumerate(chunk_vec):
            cid = f"chunk:{item['chunk_id']}"
            scores[cid] = scores.get(cid, 0) + 1.0 / (self.K + rank + 1)
            info.setdefault(cid, {"_type": "chunk", **item})

        sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)

        # 构建候选列表（送 reranker 前取 RERANK_INPUT_N 个）
        candidate_count = min(self.RERANK_INPUT_N, len(sorted_ids))
        candidates: list[dict] = []
        for i in range(candidate_count):
            eid  = sorted_ids[i]
            data = info[eid]
            candidates.append({
                "key":  eid,
                "rrf":  scores[eid],
                "data": data,
            })

        # Phase 5.x: Reranker 精排
        if len(candidates) > self.TOP_K:
            doc_texts = []
            for c in candidates:
                d = c["data"]
                if d.get("_type") == "chunk":
                    doc_texts.append(d.get("content", "")[:300])
                else:
                    doc_texts.append(
                        f"{d.get('canonical_name', '')}: {d.get('short_definition', '')}"[:300]
                    )
            try:
                scored = await self.llm.rerank(query, doc_texts, top_n=self.TOP_K)
                # 按 reranker 分数重排
                reranked: list[dict] = []
                for idx, score in scored:
                    if idx < len(candidates):
                        c = candidates[idx]
                        c["rerank_score"] = score
                        reranked.append(c)
                if reranked:
                    candidates = reranked
                    logger.debug("reranker applied",
                                candidates_in=len(doc_texts),
                                candidates_out=len(candidates))
            except Exception:
                logger.warning("rerank failed, falling back to RRF order",
                              exc_info=True)

        # 组装最终结果
        items: list[RankedKnowledgeItem] = []
        for c in candidates[:self.TOP_K]:
            data = c["data"]
            if data.get("_type") == "chunk":
                tp = data.get("title_path")
                if isinstance(tp, str):
                    try: tp = json.loads(tp)
                    except Exception: tp = []
                items.append(RankedKnowledgeItem(
                    entity_id       = c["key"],
                    rrf_score       = c["rrf"],
                    canonical_name  = tp[-1] if tp else f"文档段落 p.{data.get('page_no', '?')}",
                    short_definition = (data.get("content", ""))[:200],
                    source_type     = "chunk",
                    page_no         = data.get("page_no"),
                    title_path      = tp,
                    rerank_score    = c.get("rerank_score"),
                ))
            else:
                items.append(RankedKnowledgeItem(
                    entity_id       = c["key"],
                    rrf_score       = c["rrf"],
                    canonical_name  = data["canonical_name"],
                    short_definition = data.get("short_definition", ""),
                    rerank_score    = c.get("rerank_score"),
                ))
        return items

    async def _rewrite_query(self, query: str) -> list[str]:
        """
        5.2 轻量查询改写：将模糊学习问题转为 2-3 个检索用关键词短语。
        超时 2s 或 LLM 不可用时降级为原始 query。
        """
        prompt = (
            "将以下学习问题改写为 2-3 个检索用关键词短语，用分号分隔。"
            "只输出关键词短语，不要任何解释。\n\n"
            f"问题：{query}"
        )
        try:
            result = await asyncio.wait_for(
                self.llm.generate(prompt, model_route="knowledge_extraction"),
                timeout=2.0,
            )
            if result:
                phrases = [p.strip() for p in result.split(";") if p.strip()]
                if phrases and phrases != [query]:
                    return phrases[:3]
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug("query_rewrite_unavailable",
                         query=query[:60], error=str(e)[:100])
        return []

    async def _bm25_search(
        self, query: str,
        space_id:   str | None = None,
        domain_tag: str | None = None,
        chapter_id: str | None = None,
    ) -> list[dict]:
        # 若 chapter_id 提供但 chapter_entity_links 表不存在，则回退为不过滤
        _use_chapter = chapter_id is not None
        try:
            chapter_join = (
                "JOIN chapter_entity_links cel "
                "ON cel.entity_id = ke.entity_id "
                "AND cel.chapter_id = CAST(:chapter_id AS uuid)"
                if _use_chapter else ""
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
        except ProgrammingError:
            if _use_chapter:
                logger.warning("chapter_entity_links table missing, falling back to no-chapter BM25")
                return await self._bm25_search(query, space_id, domain_tag, None)
            raise

    async def _vector_search(
        self, query: str,
        space_id:   str | None = None,
        domain_tag: str | None = None,
        chapter_id: str | None = None,
    ) -> list[dict]:
        query_emb = await self.llm.embed_single(query)
        if not query_emb or len(query_emb) == 0:
            return []
        _use_chapter = chapter_id is not None
        try:
            chapter_join = (
                "JOIN chapter_entity_links cel "
                "ON cel.entity_id = ke.entity_id "
                "AND cel.chapter_id = CAST(:chapter_id AS uuid)"
                if _use_chapter else ""
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
        except ProgrammingError:
            if _use_chapter:
                logger.warning("chapter_entity_links table missing, falling back to no-chapter vector search")
                return await self._vector_search(query, space_id, domain_tag, None)
            raise

    async def _chunk_bm25(
        self, query: str, space_id: str | None = None,
    ) -> list[dict]:
        """6.2: BM25 全文检索 document_chunks，返回相关段落。"""
        sql = """
            SELECT dc.chunk_id::text, dc.content, dc.page_no,
                   COALESCE(dc.title_path, '[]'::jsonb) AS title_path,
                   ts_rank(
                     to_tsvector('simple', COALESCE(dc.content, '')),
                     plainto_tsquery('simple', :query)
                   ) AS score
            FROM document_chunks dc
            JOIN documents d ON d.document_id = dc.document_id
            WHERE (CAST(:space_id AS text) IS NULL OR d.space_id = CAST(:space_id AS uuid))
              AND to_tsvector('simple', COALESCE(dc.content, ''))
                  @@ plainto_tsquery('simple', :query)
            ORDER BY score DESC
            LIMIT 10
        """
        result = await self.db.execute(
            text(sql), {"query": query, "space_id": space_id}
        )
        return [dict(r._mapping) for r in result.fetchall()]

    async def _chunk_vector(
        self, query: str, space_id: str | None = None,
    ) -> list[dict]:
        """6.2: 向量检索 document_chunks embedding，返回语义相似的段落。"""
        query_emb = await self.llm.embed_single(query)
        if not query_emb or len(query_emb) == 0:
            return []
        sql = """
            SELECT dc.chunk_id::text, dc.content, dc.page_no,
                   COALESCE(dc.title_path, '[]'::jsonb) AS title_path,
                   1 - (dc.embedding <=> CAST(:emb AS vector)) AS similarity
            FROM document_chunks dc
            JOIN documents d ON d.document_id = dc.document_id
            WHERE (CAST(:space_id AS text) IS NULL OR d.space_id = CAST(:space_id AS uuid))
              AND dc.embedding IS NOT NULL
            ORDER BY dc.embedding <=> CAST(:emb AS vector)
            LIMIT 10
        """
        result = await self.db.execute(
            text(sql), {"emb": str(query_emb), "space_id": space_id}
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

        # 5.1 护栏：无检索结果时直接拒答，不浪费 LLM 调用
        if not retrieved:
            turn_id = str(uuid.uuid4())
            no_answer_text = (
                "抱歉，当前课程资料中未覆盖此问题的相关知识，我无法提供准确的回答。"
                "建议：\n\n"
                "1. 尝试用更具体的术语重新提问\n"
                "2. 上传包含相关内容的课程资料\n"
                "3. 从其他角度提问，如概念解释、原理分析等"
            )
            await self.db.execute(
                text("INSERT INTO conversation_turns (turn_id, conversation_id, role, content) "
                     "VALUES (:tid, :cid, 'user', :content)"),
                {"tid": str(uuid.uuid4()), "cid": conversation_id, "content": user_message}
            )
            await self.db.execute(
                text("INSERT INTO conversation_turns (turn_id, conversation_id, role, content, cited_entity_ids) "
                     "VALUES (:tid, :cid, 'assistant', :content, '[]'::jsonb)"),
                {"tid": turn_id, "cid": conversation_id, "content": no_answer_text}
            )
            await self.db.execute(
                text("UPDATE conversations SET turn_count = turn_count + 1, updated_at = NOW() "
                     "WHERE conversation_id = :cid"),
                {"cid": conversation_id}
            )
            await self.db.commit()
            response = {
                "conversation_id":   conversation_id,
                "turn_id":           turn_id,
                "assistant_message": no_answer_text,
                "cited_entity_ids":  [],
                "cited_sources":     [],
                "suggested_next_steps": [],
                "proactive_question": None,
                "diagnosis_update": {
                    "suspected_gap_types": [],
                    "updated_entities":    [],
                    "confidence":          0.0,
                    "error_pattern":       None,
                },
            }
            diagnosis = DiagnosisUpdate(
                suspected_gap_types=[],
                updated_entities=[],
                confidence=0.0,
                error_pattern=None,
            )
            return response, diagnosis, profile_version

        # 预计算归一化 RRF（用于低置信度护栏 + 最终 confidence）
        raw_rrf          = retrieved[0].rrf_score
        norm_score       = normalize_rrf_score(raw_rrf)
        LOW_RRF_THRESHOLD = 0.3  # 归一化 <0.3 视为弱匹配

        # LLM 教学调用（结构化输出，三级降级）
        system_prompt = TEACHING_SYSTEM_PROMPT.format(
            mastery_summary=json.dumps(mastery_summary, ensure_ascii=False)[:500],
            adaptive_strategy=build_adaptive_strategy(mastery_summary, topic_key),
            topic=topic_key,
        )
        # 5.4 来源标注：要求 LLM 在回答中标注引用的知识点
        system_prompt += (
            "\n\n## 来源标注要求\n"
            "回答中引用知识点时，请用【知识点名称】格式标注来源。"
            "例如：\u201cSQL注入的防御方法包括参数化查询【SQL注入防御】和输入验证【输入验证】\u201d。"
            "每个被引用的知识点都必须标注。\n"
        )

        # 5.1 护栏：弱证据时注入反幻觉指令
        if norm_score < LOW_RRF_THRESHOLD:
            system_prompt += (
                "\n\n## 重要约束：低证据回答\n"
                "检索到的资料与用户问题的相关性较弱。"
                "如果以下知识不足以回答用户问题，请明确说"
                "\u201c当前课程资料中未覆盖此问题\u201d，不要猜测或编造信息。"
                "如果部分相关，请先声明知识的局限性再回答。\n"
            )
        teach_resp: TeachResponse = await self.llm.teach(
            model_route      = model_route,
            system_prompt    = system_prompt,
            messages         = messages,
            user_message     = user_message,
            knowledge_context = retrieved,
        )

        # 计算置信度（RRF 归一化后参与计算）
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
            "cited_sources":     [
                {
                    "entity_name":              r.canonical_name,
                    "short_definition_preview": (r.short_definition or "")[:200],
                }
                for r in retrieved[:3]
            ],
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
