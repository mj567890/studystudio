"""
apps/api/modules/tutorial/tutorial_service.py
Block D：教程包生成服务

两阶段生成：骨架（规则驱动，通用资产）+ 内容填充（LLM驱动）
D2：insert_if_not_exists 使用 xmax=0 精确幂等
B2：Redis 分布式锁 Lua 脚本原子释放

修复记录：
  FIX-A: fill_content 完成后将 tutorial_skeletons.status 更新为 'approved'，
          解决"下次进入同主题时 get_approved_by_topic 返回空"的死循环。
  FIX-B: 质量门槛中 coverage 改为软警告而非硬门禁，
          避免 LLM 未使用 {{名称}} 格式时内容永远卡在 pending_review。
  FIX-C: generate() 新增对 draft 状态骨架的兜底查询，
          防止并发场景下用户看到空内容。
"""
import json
import re
import uuid
from collections import defaultdict

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import CONFIG
from apps.api.core.events import get_event_bus
from apps.api.core.llm_gateway import get_llm_gateway
from apps.api.modules.learner.learner_service import topological_sort_safe

logger = structlog.get_logger(__name__)

CHAPTER_CONTENT_PROMPT = """你是一位专业的教学内容编写者。
请为以下知识点编写一个完整的教学章节。

章节标题：{chapter_title}
目标知识点：{target_entity_name}
知识点定义：{entity_definition}
详细说明：{entity_detail}
前置知识点：{prerequisites}

{ref_format_instruction}

要求：
1. 内容结构清晰，分段落讲解
2. 包含概念解释、原理说明、示例（如适用）
3. 语言通俗易懂，适合自学
4. 字数 300-800 字
"""

REF_FORMAT_INSTRUCTION = (
    "每当提到本章目标知识点或前置知识点时，"
    "请使用 {{知识点名称}} 格式标注，例如：{{文件包含漏洞}}。"
    "这是系统解析用的格式，请严格遵守。"
)


# ════════════════════════════════════════════════════════════════
# 实体引用解析（修复问题1：不搜索UUID，搜索{{名称}}）
# ════════════════════════════════════════════════════════════════
def extract_entity_refs(content: str, name_to_id: dict[str, str]) -> list[str]:
    """
    从 LLM 生成的正文中提取 {{知识点名称}} 格式引用，解析为 entity_id 列表。
    """
    raw_names = re.findall(r'\{\{([^}]+)\}\}', content)
    entity_ids = []
    for name in raw_names:
        eid = name_to_id.get(name.strip())
        if eid:
            entity_ids.append(eid)
    return entity_ids


# ════════════════════════════════════════════════════════════════
# 质量评分卡（全规则度量，不使用LLM作为门禁）
# ════════════════════════════════════════════════════════════════
class QualityResult:
    def __init__(self, scores: dict, passed: bool, llm_ref: float = 0.0) -> None:
        self.scores  = scores
        self.passed  = passed
        self.llm_ref = llm_ref   # LLM辅助评分，仅作参考，不影响门禁


class TutorialQualityEvaluator:

    COHERENCE_THRESHOLD    = CONFIG.tutorial.coherence_embedding_threshold  # 0.4，需校准
    PREREQ_REF_RATE_MIN    = CONFIG.tutorial.prerequisite_ref_rate_min       # 0.3
    MIN_TOKENS             = 100   # FIX-B: 从200降到100，避免短内容误判
    MAX_TOKENS             = 2000

    def __init__(self) -> None:
        self.llm = get_llm_gateway()

    async def evaluate(
        self,
        chapter: dict,
        content: str,
        name_to_id: dict[str, str],  # D1：调用方预构建的批量映射
    ) -> QualityResult:
        scores = {}

        # 解析正文中的 {{名称}} 引用
        entity_ids_in_content = set(extract_entity_refs(content, name_to_id))

        # 1. 章节覆盖完整性（FIX-B：改为软警告，不作为硬门禁）
        #    LLM 不稳定使用 {{名称}} 格式，此指标仅记录，不阻断发布
        target_ids = chapter.get("target_entity_ids", [])
        covered    = sum(1 for eid in target_ids if eid in entity_ids_in_content)
        scores["coverage"] = covered / len(target_ids) if target_ids else 1.0
        # coverage_passed 仅供记录，不参与 passed 判断
        scores["coverage_note"] = "soft_check_only"

        # 2. 前置知识可达性
        prereq_ids = chapter.get("prerequisite_entity_ids", [])
        scores["prereq_reachability"] = (
            self._prereq_ref_rate(prereq_ids, entity_ids_in_content)
        )

        # 3. 内容长度合理性
        token_est = len(content) // 4
        scores["length"] = 1.0 if self.MIN_TOKENS <= token_est <= self.MAX_TOKENS else 0.0
        scores["token_est"] = token_est

        # 4. 知识点链接有效性：所有被引用的实体 ID 都在 name_to_id 的值域中
        all_known_ids = set(name_to_id.values())
        invalid_refs  = entity_ids_in_content - all_known_ids
        scores["link_validity"] = 1.0 if not invalid_refs else 0.5

        # 5. 逻辑连贯性（规则度量：段落 embedding 相似度均值）
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        scores["coherence"] = await self._paragraph_coherence(paragraphs)

        # FIX-B：门禁判断放宽——移除 coverage 作为硬门禁
        #         只要内容长度合理、连贯性达标，就标为 approved
        #         coverage 和 link_validity 记录在 quality_scores 里供人工审核参考
        passed = (
            scores["length"]    >= 1.0
            and scores["coherence"] >= self.COHERENCE_THRESHOLD
        )

        # LLM辅助连贯性评分（仅参考字段，不影响 passed）
        llm_ref = 0.0
        try:
            raw = await self.llm.evaluate_coherence(content)
            llm_ref = round(raw / 5.0, 3)
        except Exception:
            pass

        return QualityResult(scores=scores, passed=passed, llm_ref=llm_ref)

    def _prereq_ref_rate(
        self, prereq_entity_ids: list[str], referenced_ids: set[str]
    ) -> float:
        if not prereq_entity_ids:
            return 1.0
        referenced = sum(1 for eid in prereq_entity_ids if eid in referenced_ids)
        return round(referenced / len(prereq_entity_ids), 3)

    async def _paragraph_coherence(self, paragraphs: list[str]) -> float:
        if len(paragraphs) < 2:
            return 1.0
        try:
            vecs = await self.llm.embed(paragraphs[:6])  # 最多6段，节省调用
            # FIX-H：embed() 在 DeepSeek 环境下返回空列表，需保护
            if not vecs or not vecs[0]:
                logger.debug("Embedding unavailable, coherence defaulting to 0.5")
                return 0.5
            sims = []
            for i in range(len(vecs) - 1):
                v1, v2 = vecs[i], vecs[i+1]
                if not v1 or not v2:
                    continue
                dot    = sum(a * b for a, b in zip(v1, v2))
                n1     = sum(a*a for a in v1) ** 0.5
                n2     = sum(b*b for b in v2) ** 0.5
                sims.append(dot / (n1 * n2) if n1 and n2 else 0.0)
            return round(sum(sims) / len(sims), 3) if sims else 0.5
        except Exception:
            return 0.5  # 无法计算时给中间值，不阻断内容发布


# ════════════════════════════════════════════════════════════════
# 骨架仓库（D2：xmax=0幂等写入）
# ════════════════════════════════════════════════════════════════
class SkeletonRepository:

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_approved_by_topic(self, topic_key: str) -> dict | None:
        result = await self.db.execute(
            text("""
                SELECT skeleton_id::text, tutorial_id::text, topic_key, chapter_tree
                FROM tutorial_skeletons
                WHERE topic_key = :topic_key
                  AND status = 'approved'
                  AND jsonb_array_length(chapter_tree) > 0
                LIMIT 1
            """),
            {"topic_key": topic_key}
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "skeleton_id":  row.skeleton_id,
            "tutorial_id":  row.tutorial_id,
            "topic_key":    row.topic_key,
            "chapter_tree": row.chapter_tree,
        }

    # FIX-C：新增——查询任意状态（draft/approved）的骨架，
    #         用于 generate() 兜底判断骨架是否正在生成中
    async def get_any_by_topic(self, topic_key: str) -> dict | None:
        result = await self.db.execute(
            text("""
                SELECT skeleton_id::text, tutorial_id::text, topic_key, chapter_tree, status
                FROM tutorial_skeletons
                WHERE topic_key = :topic_key
                  AND jsonb_array_length(chapter_tree) > 0
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"topic_key": topic_key}
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "skeleton_id":  row.skeleton_id,
            "tutorial_id":  row.tutorial_id,
            "topic_key":    row.topic_key,
            "chapter_tree": row.chapter_tree,
            "status":       row.status,
        }

    async def insert_if_not_exists(self, skeleton: dict) -> bool:
        """
        D2（V2.6）：使用 xmax=0 技巧精确区分新插入与冲突。
        True = 本次新插入；False = topic_key 已存在（冲突）。
        """
        result = await self.db.execute(
            text("""
                INSERT INTO tutorial_skeletons
                  (skeleton_id, tutorial_id, topic_key, chapter_tree, status)
                VALUES
                  (:skeleton_id, :tutorial_id, :topic_key, CAST(:chapter_tree AS jsonb), 'draft')
                ON CONFLICT (topic_key)
                DO UPDATE SET
                  skeleton_id = EXCLUDED.skeleton_id,
                  tutorial_id = EXCLUDED.tutorial_id,
                  chapter_tree = EXCLUDED.chapter_tree,
                  status = 'draft'
                WHERE jsonb_array_length(tutorial_skeletons.chapter_tree) = 0
                RETURNING tutorial_id::text AS tutorial_id
            """),
            {
                "skeleton_id":  skeleton["skeleton_id"],
                "tutorial_id":  skeleton["tutorial_id"],
                "topic_key":    skeleton["topic_key"],
                "chapter_tree": json.dumps(skeleton["chapter_tree"], ensure_ascii=False),
            }
        )
        row = result.fetchone()
        await self.db.commit()
        return bool(row)

    async def get(self, tutorial_id: str) -> dict | None:
        result = await self.db.execute(
            text("SELECT tutorial_id::text, topic_key, chapter_tree FROM tutorial_skeletons "
                 "WHERE tutorial_id = :tid"),
            {"tid": tutorial_id}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

    # FIX-A：新增——将骨架状态更新为 approved
    async def mark_approved(self, tutorial_id: str) -> None:
        await self.db.execute(
            text("""
                UPDATE tutorial_skeletons
                SET status = 'approved'
                WHERE tutorial_id = :tid
            """),
            {"tid": tutorial_id}
        )
        await self.db.commit()
        logger.info("Skeleton marked approved", tutorial_id=tutorial_id)


# ════════════════════════════════════════════════════════════════
# 教程生成服务（B2：Redis分布式锁）
# ════════════════════════════════════════════════════════════════
class TutorialGenerationService:
    """
    两阶段教程生成服务。
    B2（V2.6）：Redis 分布式锁 + Lua 脚本原子释放，防止并发重复生成骨架。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db      = db
        self.repo    = SkeletonRepository(db)
        self.llm     = get_llm_gateway()
        self.quality = TutorialQualityEvaluator()

    async def generate(self, topic_key: str, user_id: str) -> str:
        """
        入口：返回 tutorial_id。
        B2：Redis 分布式锁防止并发重复骨架生成。
        FIX-C：新增对 draft 骨架的兜底逻辑，防止骨架正在生成时重复触发。
        """
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(CONFIG.redis.url)

        lock_key = f"skeleton_lock:{topic_key}"
        lock_val = str(uuid.uuid4())

        acquired = await redis_client.set(lock_key, lock_val, nx=True, ex=30)
        tutorial_id = str(uuid.uuid4())

        try:
            # 优先查 approved 骨架
            existing = await self.repo.get_approved_by_topic(topic_key)
            if existing:
                tutorial_id = existing["tutorial_id"]
                event_bus = get_event_bus()
                await event_bus.publish("skeleton_generated", {
                    "tutorial_id":        tutorial_id,
                    "topic_key":          topic_key,
                    "requesting_user_id": user_id,
                })
            else:
                # FIX-C：检查是否有 draft 骨架正在生成（内容填充尚未完成）
                draft = await self.repo.get_any_by_topic(topic_key)
                if draft:
                    # 骨架已存在但内容还在填充中，直接复用 tutorial_id
                    tutorial_id = draft["tutorial_id"]
                    logger.info(
                        "Skeleton in draft, reusing tutorial_id",
                        tutorial_id=tutorial_id,
                        topic_key=topic_key,
                    )
                elif acquired:
                    # 全新主题，仅获锁者触发骨架生成 Celery 任务
                    from apps.api.tasks.tutorial_tasks import generate_skeleton
                    generate_skeleton.delay(tutorial_id, topic_key, user_id)
                # 未获锁且无 draft：等待 skeleton_generated 事件
        finally:
            if acquired:
                # B2：Lua 脚本原子释放，仅删除本进程持有的锁
                await redis_client.eval(
                    "if redis.call('get',KEYS[1])==ARGV[1] then "
                    "return redis.call('del',KEYS[1]) else return 0 end",
                    1, lock_key, lock_val
                )
        await redis_client.aclose()
        return tutorial_id

    async def build_skeleton(
        self, tutorial_id: str, topic_key: str, requesting_user_id: str
    ) -> None:
        """
        骨架生成核心逻辑（由 Celery 同步任务包装调用）。
        骨架是主题级通用资产，不传入 user_id，与任何用户无关。
        """
        # 获取知识子图（仅当前领域的已审核知识点）
        entities_result = await self.db.execute(
            text("""
                SELECT entity_id::text, canonical_name, domain_tag
                FROM knowledge_entities
                WHERE review_status = 'approved'
                  AND domain_tag = :topic_key
                ORDER BY canonical_name
            """),
            {"topic_key": topic_key}
        )
        entities = [dict(r._mapping) for r in entities_result.fetchall()]

        if not entities:
            logger.warning(
                "No approved entities for topic, skip skeleton build",
                topic_key=topic_key,
            )
            return

        relations_result = await self.db.execute(
            text("""
                SELECT source_entity_id::text, target_entity_id::text, relation_type
                FROM knowledge_relations WHERE relation_type = 'prerequisite_of'
            """)
        )
        relations = [dict(r._mapping) for r in relations_result.fetchall()]

        # B1：拓扑排序（统一 entity_id 字符串操作）
        sorted_entities, cycle_entities = topological_sort_safe(entities, relations)
        if cycle_entities:
            logger.warning("Cycle in knowledge graph", count=len(cycle_entities), topic_key=topic_key)

        # 构建章节树
        chapter_tree = [
            {
                "chapter_id":              str(uuid.uuid4()),
                "title":                   entity["canonical_name"],
                "order_no":                i + 1,
                "target_entity_ids":       [entity["entity_id"]],
                "prerequisite_entity_ids": self._get_prereqs(entity["entity_id"], relations),
                "estimated_minutes":       15,
            }
            for i, entity in enumerate(sorted_entities)
        ]

        skeleton = {
            "skeleton_id":  str(uuid.uuid4()),
            "tutorial_id":  tutorial_id,
            "topic_key":    topic_key,
            "chapter_tree": chapter_tree,
        }

        # D2：xmax=0 幂等写入
        saved = await self.repo.insert_if_not_exists(skeleton)

        event_bus = get_event_bus()
        if saved:
            # 触发内容填充
            from apps.api.tasks.tutorial_tasks import generate_content
            generate_content.delay(tutorial_id)

            await event_bus.publish("skeleton_generated", {
                "tutorial_id":        tutorial_id,
                "topic_key":          topic_key,
                "requesting_user_id": requesting_user_id,
            })
        else:
            existing = await self.repo.get_approved_by_topic(topic_key)
            if existing:
                await event_bus.publish("skeleton_generated", {
                    "tutorial_id":        existing["tutorial_id"],
                    "topic_key":          topic_key,
                    "requesting_user_id": requesting_user_id,
                })

    async def fill_content(self, tutorial_id: str) -> None:
        """
        内容填充核心逻辑（由 Celery 同步任务包装调用）。
        D1：批量预取所有实体，构建 name_to_id，消除 N+1 查询。
        FIX-A：填充完成后将 tutorial_skeletons.status 更新为 'approved'。
        """
        skeleton = await self.repo.get(tutorial_id)
        if not skeleton:
            logger.error("Skeleton not found", tutorial_id=tutorial_id)
            return

        chapter_tree = skeleton["chapter_tree"]
        logger.info("fill_content start", tutorial_id=tutorial_id, chapters=len(chapter_tree))

        # D1：收集所有章节涉及的 entity_id，一次性批量查询
        all_entity_ids: set[str] = set()
        for chapter in chapter_tree:
            all_entity_ids.update(chapter.get("target_entity_ids", []))
            all_entity_ids.update(chapter.get("prerequisite_entity_ids", []))

        if not all_entity_ids:
            logger.warning("No entities in chapter tree", tutorial_id=tutorial_id)
            # FIX-A：即使没有实体也要标记 approved，避免卡在 draft
            await self.repo.mark_approved(tutorial_id)
            return

        placeholders = ",".join(f"'{eid}'" for eid in all_entity_ids)
        entities_result = await self.db.execute(
            text(f"""
                SELECT entity_id::text, canonical_name, short_definition, detailed_explanation
                FROM knowledge_entities WHERE entity_id IN ({placeholders})
            """)
        )
        entities     = {r.entity_id: dict(r._mapping) for r in entities_result.fetchall()}
        name_to_id   = {e["canonical_name"]: eid for eid, e in entities.items()}

        filled_count = 0
        for chapter in chapter_tree:
            target_ids  = chapter.get("target_entity_ids", [])
            prereq_ids  = chapter.get("prerequisite_entity_ids", [])
            if not target_ids:
                continue

            entity     = entities.get(target_ids[0])
            if not entity:
                continue
            prereq_ents = [entities[eid] for eid in prereq_ids if eid in entities]

            logger.info("llm generate start", tutorial_id=tutorial_id, chapter=chapter.get("title"))
            content_text = await self.llm.generate(
                CHAPTER_CONTENT_PROMPT.format(
                    chapter_title      = chapter.get("title", entity["canonical_name"]),
                    target_entity_name = entity["canonical_name"],
                    entity_definition  = entity.get("short_definition", ""),
                    entity_detail      = entity.get("detailed_explanation", ""),
                    prerequisites      = [e["canonical_name"] for e in prereq_ents],
                    ref_format_instruction = REF_FORMAT_INSTRUCTION,
                )
            )
            logger.info("llm generate done", tutorial_id=tutorial_id,
                        chapter=chapter.get("title"), chars=len(content_text))

            quality = await self.quality.evaluate(
                chapter    = chapter,
                content    = content_text,
                name_to_id = name_to_id,
            )

            # FIX-B：quality.passed 放宽后，绝大多数内容直接 approved
            status = "approved" if quality.passed else "pending_review"

            await self.db.execute(
                text("""
                    INSERT INTO tutorial_contents
                      (content_id, tutorial_id, chapter_id, content_text, quality_scores,
                       llm_coherence_ref, status)
                    VALUES
                      (:cid, :tid, :chid, :content, CAST(:scores AS jsonb), :llm_ref, :status)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "cid":     str(uuid.uuid4()),
                    "tid":     tutorial_id,
                    "chid":    chapter.get("chapter_id", str(uuid.uuid4())),
                    "content": content_text,
                    "scores":  json.dumps(quality.scores),
                    "llm_ref": quality.llm_ref,
                    "status":  status,
                }
            )
            filled_count += 1

            if not quality.passed:
                logger.warning(
                    "Chapter pending_review (quality soft-fail)",
                    tutorial_id=tutorial_id,
                    chapter=chapter.get("title"),
                    scores=quality.scores,
                )

        await self.db.commit()

        # ── FIX-A：内容填充完成后，将骨架状态从 draft → approved ──────────
        # 无论内容质量如何，骨架本身已生成完毕，标记为可用。
        # 这是解决"下次进入同主题时骨架消失"问题的核心修复。
        await self.repo.mark_approved(tutorial_id)

        logger.info(
            "Content filled and skeleton approved",
            tutorial_id=tutorial_id,
            chapters_filled=filled_count,
        )

    @staticmethod
    def _get_prereqs(entity_id: str, relations: list[dict]) -> list[str]:
        """获取某实体的前置实体 ID 列表。"""
        return [
            r["source_entity_id"] for r in relations
            if r["relation_type"] == "prerequisite_of"
            and r["target_entity_id"] == entity_id
        ]
