"""
apps/api/modules/learner/learner_service.py
Block C：学习者画像与诊断模块

包含：
- MasteryStateService：掌握度状态管理（含指数衰减）
- ColdStartService：冷启动定位自检（题库预生成 + 零LLM兜底）
- GapScanService：漏洞扫描（生成 gap_report）
- RepairPathService：补洞路径（B1 topological_sort_safe + B3 dependency_depth）
"""
import json
import math
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.events import get_event_bus
from packages.shared_schemas.enums import (
    GapType,
    PLACEMENT_SCORE_MAP,
    MasteryLevel,
)

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# 掌握度状态服务
# ════════════════════════════════════════════════════════════════
class MasteryStateService:
    """管理 learner_knowledge_states 表的读写与衰减计算。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_mastered_entities(
        self, user_id: str, threshold: float = 0.7
    ) -> list[dict]:
        """
        获取已掌握节点（mastery_score >= threshold）。
        注意：剪枝阈值 0.7 与展示阈值 0.8 不同，均为有意设计。
        """
        result = await self.db.execute(
            text("""
                SELECT entity_id, mastery_score, last_reviewed_at
                FROM learner_knowledge_states
                WHERE user_id = :user_id AND mastery_score >= :threshold
            """),
            {"user_id": user_id, "threshold": threshold}
        )
        return [
            {"entity_id": str(r.entity_id),
             "mastery_score": r.mastery_score,
             "last_reviewed_at": r.last_reviewed_at}
            for r in result.fetchall()
        ]

    async def bulk_upsert(self, user_id: str, states: list[dict]) -> None:
        """批量更新掌握度，使用 ON CONFLICT DO UPDATE。"""
        for state in states:
            await self.db.execute(
                text("""
                    INSERT INTO learner_knowledge_states
                      (id, user_id, entity_id, mastery_score, decay_rate, last_reviewed_at)
                    VALUES
                      (:id, :user_id, :entity_id, :mastery_score, :decay_rate, NOW())
                    ON CONFLICT (user_id, entity_id)
                    DO UPDATE SET
                      mastery_score    = EXCLUDED.mastery_score,
                      last_reviewed_at = NOW(),
                      review_count     = learner_knowledge_states.review_count + 1
                """),
                {
                    "id":           str(uuid.uuid4()),
                    "user_id":      user_id,
                    "entity_id":    state["entity_id"],
                    "mastery_score": state["mastery_score"],
                    "decay_rate":   state.get("decay_rate", 0.1),
                }
            )
        await self.db.commit()

    def apply_decay(self, score: float, decay_rate: float, days_since: float) -> float:
        """
        指数衰减模型：score_t = score_0 × e^(-λ × t)
        λ = decay_rate，t = 距上次学习的天数
        """
        if days_since <= 0:
            return score
        decayed = score * math.exp(-decay_rate * days_since)
        return max(0.0, round(decayed, 4))


# ════════════════════════════════════════════════════════════════
# 冷启动服务
# ════════════════════════════════════════════════════════════════
class ColdStartService:
    """
    冷启动定位自检。
    题库由离线 Celery 任务预生成（prebuild_placement_bank），
    用户请求时直接读缓存，P95 < 50ms。
    无题库时以规则兜底，零 LLM 调用。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_placement_quiz(self, topic_key: str) -> dict:
        """获取冷启动题目。优先读取预生成题库，否则返回兜底简化题。"""
        result = await self.db.execute(
            text("""
                SELECT questions_by_domain, is_ready
                FROM placement_question_banks
                WHERE topic_key = :topic_key
            """),
            {"topic_key": topic_key}
        )
        row = result.fetchone()

        if row and row.is_ready:
            questions_by_domain = row.questions_by_domain
            questions = []
            for domain, domain_questions in questions_by_domain.items():
                questions.extend(domain_questions[:2])  # 每领域最多2题
            return {
                "quiz_type":  "placement",
                "topic_key":  topic_key,
                "is_fallback": False,
                "questions":  questions[:12],  # 最多12题
            }

        # 兜底：从核心实体构造简化题（零 LLM 调用）
        return await self._fallback_quiz(topic_key)

    async def _fallback_quiz(self, topic_key: str) -> dict:
        """
        零 LLM 兜底方案：从 is_core=true 的实体生成简单认知调查题。
        """
        result = await self.db.execute(
            text("""
                SELECT entity_id, canonical_name, domain_tag
                FROM knowledge_entities
                WHERE is_core = true AND review_status = 'approved'
                ORDER BY RANDOM()
                LIMIT 4
            """)
        )
        rows = result.fetchall()
        questions = [
            {
                "question_id": str(uuid.uuid4()),
                "domain":      row.domain_tag,
                "difficulty":  "basic",
                "stem":        f"你是否了解「{row.canonical_name}」？",
                "options": [
                    "A. 完全了解",
                    "B. 有所了解，但不深入",
                    "C. 听说过，但不清楚",
                    "D. 完全不了解",
                ],
                "is_fallback": True,
            }
            for row in rows
        ]
        return {
            "quiz_type":  "placement",
            "topic_key":  topic_key,
            "is_fallback": True,
            "questions":  questions,
        }

    async def process_placement_result(
        self, user_id: str, topic_key: str, answers: list[dict]
    ) -> dict:
        """
        处理冷启动答题结果，初始化掌握度状态。
        按 (basic_correct, advanced_correct) 映射初始掌握度。
        """
        # 整理答题结果：{domain: {difficulty: is_correct}}
        result_map: dict[str, dict[str, bool]] = {}

        for answer in answers:
            question_id = answer.get("question_id", "")
            selected    = answer.get("selected_option", "")
            domain      = answer.get("domain", "")
            difficulty  = answer.get("difficulty", "basic")

            # 简化评分：A/B 选项视为"正确"（了解），C/D 视为"不了解"
            if answer.get("is_fallback"):
                is_correct = selected in ("A", "B")
            else:
                is_correct = answer.get("is_correct", False)

            result_map.setdefault(domain, {})[difficulty] = is_correct

        # 按领域计算初始掌握度
        domain_scores: dict[str, float] = {}
        for domain, results in result_map.items():
            basic_ok    = results.get("basic", False)
            advanced_ok = results.get("advanced", False)
            domain_scores[domain] = PLACEMENT_SCORE_MAP[(basic_ok, advanced_ok)]

        # 获取该主题下的所有实体，批量初始化掌握度
        entities_result = await self.db.execute(
            text("""
                SELECT entity_id, domain_tag
                FROM knowledge_entities
                WHERE review_status = 'approved'
            """)
        )
        entities = entities_result.fetchall()

        states = []
        for entity in entities:
            domain = entity.domain_tag
            score  = domain_scores.get(domain, 0.15)  # 未测试的领域给最低分
            states.append({
                "entity_id":    str(entity.entity_id),
                "mastery_score": score,
                "decay_rate":   0.1,
            })

        mastery_svc = MasteryStateService(self.db)
        await mastery_svc.bulk_upsert(user_id, states)

        # 发布学习状态更新事件
        event_bus = get_event_bus()
        await event_bus.publish("learner_state_updated", {
            "user_id":          user_id,
            "topic_key":        topic_key,
            "changed_entities": [s["entity_id"] for s in states],
            "domain_scores":    domain_scores,
        })

        return {
            "mastery_initialized": True,
            "entity_count":        len(states),
            "domain_scores":       domain_scores,
            "profile_updated_at":  datetime.now(timezone.utc).isoformat(),
        }


# ════════════════════════════════════════════════════════════════
# 漏洞扫描服务
# ════════════════════════════════════════════════════════════════
class GapScanService:
    """扫描学习者知识漏洞，生成 gap_report。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def scan(self, user_id: str, topic_key: str) -> dict:
        """
        扫描该主题下所有知识点的掌握度，按阈值分类。
        - weak_points:     mastery_score < 0.5
        - uncertain_points: 0.5 <= mastery_score < 0.8
        - mastered_points:  mastery_score >= 0.8  （展示阈值 0.8）
        """
        result = await self.db.execute(
            text("""
                SELECT ke.entity_id, ke.canonical_name, ke.domain_tag,
                       COALESCE(lks.mastery_score, 0.0) AS mastery_score,
                       lks.last_reviewed_at
                FROM knowledge_entities ke
                LEFT JOIN learner_knowledge_states lks
                  ON ke.entity_id = lks.entity_id AND lks.user_id = :user_id
                WHERE ke.review_status = 'approved'
                ORDER BY ke.domain_tag, mastery_score ASC
            """),
            {"uid": user_id}
        )
        rows = result.fetchall()

        weak_points, uncertain_points, mastered_points = [], [], []
        for row in rows:
            score = row.mastery_score or 0.0
            item = {
                "entity_id":        str(row.entity_id),
                "canonical_name":   row.canonical_name,
                "domain_tag":       row.domain_tag,
                "mastery_score":    score,
            }
            if score < 0.5:
                item["gap_types"] = [GapType.DEFINITION]  # 默认推断为定义型障碍
                item["priority"]  = 1 if score < 0.2 else 2
                weak_points.append(item)
            elif score < 0.8:
                item["gap_types"] = [GapType.MECHANISM]
                item["priority"]  = 3
                uncertain_points.append(item)
            else:
                item["mastery_level"] = MasteryLevel.HIGH
                mastered_points.append(item)

        gap_report = {
            "user_id":          user_id,
            "topic_key":        topic_key,
            "weak_points":      weak_points[:20],      # 最多返回20个薄弱点
            "uncertain_points": uncertain_points[:10],
            "mastered_points":  mastered_points,
            "generated_at":     datetime.now(timezone.utc).isoformat(),
        }

        # 发布 gap_report_generated 事件
        event_bus = get_event_bus()
        await event_bus.publish("gap_report_generated", {
            "user_id":       user_id,
            "topic_key":     topic_key,
            "weak_count":    len(weak_points),
            "mastered_count": len(mastered_points),
        })

        return gap_report


# ════════════════════════════════════════════════════════════════
# B1：拓扑排序（统一使用 entity_id 字符串操作）
# ════════════════════════════════════════════════════════════════
def topological_sort_safe(
    entities: list[dict], relations: list[dict]
) -> tuple[list[dict], list[dict]]:
    """
    B1（V2.6）：Kahn 算法拓扑排序，全程使用 entity_id 字符串操作。
    返回 (sorted_entities, cycle_entities)。
    """
    entity_map = {e["entity_id"]: e for e in entities}
    in_degree  = {eid: 0 for eid in entity_map}
    adj        = defaultdict(list)

    for r in relations:
        if r.get("relation_type") == "prerequisite_of":
            src, tgt = r["source_entity_id"], r["target_entity_id"]
            if src in entity_map and tgt in entity_map:
                adj[src].append(tgt)
                in_degree[tgt] = in_degree.get(tgt, 0) + 1

    queue      = deque(eid for eid, deg in in_degree.items() if deg == 0)
    result_ids: list[str] = []

    while queue:
        eid = queue.popleft()
        result_ids.append(eid)
        for neighbor in adj[eid]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    sorted_id_set = set(result_ids)
    cycle_ids     = [eid for eid in entity_map if eid not in sorted_id_set]

    sorted_entities = [entity_map[eid] for eid in result_ids]
    cycle_entities  = [entity_map[eid] for eid in cycle_ids]
    return sorted_entities + cycle_entities, cycle_entities


# ════════════════════════════════════════════════════════════════
# B3：PathStep 数据类
# ════════════════════════════════════════════════════════════════
class PathStep:
    """B3（V2.6）：包含 dependency_depth 字段，支持按优先级截断。"""
    def __init__(
        self,
        step_no:          int,
        type:             str,
        ref_id:           str,
        title:            str,
        dependency_depth: int = 0,
    ) -> None:
        self.step_no          = step_no
        self.type             = type
        self.ref_id           = ref_id
        self.title            = title
        self.dependency_depth = dependency_depth

    def dict(self) -> dict:
        return {
            "step_no":          self.step_no,
            "type":             self.type,
            "ref_id":           self.ref_id,
            "title":            self.title,
            "dependency_depth": self.dependency_depth,
        }


# ════════════════════════════════════════════════════════════════
# 补洞路径服务
# ════════════════════════════════════════════════════════════════
class RepairPathService:
    """
    基于掌握度剪枝的前置可达性保障算法。
    B1 + B3（V2.6）：使用 topological_sort_safe + PathStep.dependency_depth。
    """

    MAX_PATH_STEPS = 20

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def compute(
        self,
        user_id:         str,
        topic_key:       str,
        current_target:  str | None = None,
    ) -> dict:
        # ── 新路径：有已发布蓝图时返回 chapter 级路径 ──────────────
        bp_row = await self.db.execute(
            text("""
                SELECT sb.blueprint_id::text
                FROM skill_blueprints sb
                WHERE sb.topic_key = :tk AND sb.status = 'published'
                LIMIT 1
            """),
            {"tk": topic_key}
        )
        bp = bp_row.fetchone()
        if bp:
            return await self._compute_chapter_path(user_id, topic_key, str(bp[0]))

        # ── 旧路径：无已发布蓝图时返回空路径 ──────────────────
        return {
            "user_id":      user_id,
            "topic_key":    topic_key,
            "path_type":    "none",
            "path_steps":   [],
            "is_truncated": False,
            "total_steps":  0,
            "message":      "该领域暂无学习路径，请先点击「生成路径」",
        }

        # ── 以下旧路径代码已停用 ──────────────────────────────────────────
        # 1. 获取已掌握节点（剪枝阈值 0.7，宽松，减少冗余步骤）
        mastery_svc = MasteryStateService(self.db)
        mastered    = await mastery_svc.get_mastered_entities(user_id, threshold=0.7)
        mastered_ids = {m["entity_id"] for m in mastered}

        # 2. 仅获取当前主题的已审核实体，避免学习路径与教程串题
        entities_result = await self.db.execute(
            text("""
                SELECT entity_id::text AS entity_id, canonical_name, domain_tag
                FROM knowledge_entities
                WHERE review_status = 'approved'
                  AND domain_tag = :topic_key
                ORDER BY canonical_name
            """),
            {"topic_key": topic_key}
        )
        all_entities = [dict(r._mapping) for r in entities_result.fetchall()]
        allowed_entity_ids = {e["entity_id"] for e in all_entities}

        if not all_entities:
            event_bus = get_event_bus()
            await event_bus.publish("repair_path_generated", {
                "user_id":      user_id,
                "topic_key":    topic_key,
                "step_count":   0,
                "is_truncated": False,
            })
            return {
                "user_id":             user_id,
                "topic_key":           topic_key,
                "required_entity_ids": [],
                "path_steps":          [],
                "is_truncated":        False,
                "total_steps":         0,
            }

        # 3. 获取依赖关系，并限制在当前主题子图内
        relations_result = await self.db.execute(
            text("""
                SELECT source_entity_id::text, target_entity_id::text, relation_type
                FROM knowledge_relations
                WHERE relation_type = 'prerequisite_of'
            """)
        )
        all_relations = [
            {"source_entity_id": str(r.source_entity_id),
             "target_entity_id": str(r.target_entity_id),
             "relation_type":    r.relation_type}
            for r in relations_result.fetchall()
            if str(r.source_entity_id) in allowed_entity_ids
            and str(r.target_entity_id) in allowed_entity_ids
        ]

        # 4. BFS 带剪枝的依赖回溯
        target_entities = [e for e in all_entities if e["entity_id"] not in mastered_ids]
        required: set[str] = set()
        queue   = deque(e["entity_id"] for e in target_entities)
        visited : set[str] = set()

        adj_prereq: dict[str, list[str]] = defaultdict(list)
        for r in all_relations:
            adj_prereq[r["target_entity_id"]].append(r["source_entity_id"])

        while queue:
            eid = queue.popleft()
            if eid in visited or eid in mastered_ids:
                continue
            visited.add(eid)
            required.add(eid)
            for pre_id in adj_prereq.get(eid, []):
                if pre_id not in mastered_ids and pre_id not in visited:
                    queue.append(pre_id)

        # 5. B1：拓扑排序（使用 entity_id 字符串，正确检测循环依赖）
        required_entities  = [e for e in all_entities if e["entity_id"] in required]
        required_relations = [r for r in all_relations
                              if r["source_entity_id"] in required
                              and r["target_entity_id"] in required]
        sorted_entities, cycle_entities = topological_sort_safe(
            required_entities, required_relations
        )
        if cycle_entities:
            logger.warning("Cycle detected in knowledge graph",
                           count=len(cycle_entities))

        # 6. 计算拓扑深度
        depth_map = self._compute_depths(required_entities, required_relations)

        # 7. B3：构建 PathStep 列表（含 dependency_depth）
        all_steps = [
            PathStep(
                step_no          = i + 1,
                type             = "entity",
                ref_id           = e["entity_id"],
                title            = e["canonical_name"],
                dependency_depth = depth_map.get(e["entity_id"], 0),
            )
            for i, e in enumerate(sorted_entities)
        ]

        # 截断：按拓扑深度排序，优先最基础节点
        is_truncated = len(all_steps) > self.MAX_PATH_STEPS
        if is_truncated:
            path_steps = sorted(all_steps, key=lambda s: s.dependency_depth)[:self.MAX_PATH_STEPS]
        else:
            path_steps = all_steps

        # 发布 repair_path_generated 事件
        event_bus = get_event_bus()
        await event_bus.publish("repair_path_generated", {
            "user_id":     user_id,
            "topic_key":   topic_key,
            "step_count":  len(path_steps),
            "is_truncated": is_truncated,
        })

        return {
            "user_id":               user_id,
            "topic_key":             topic_key,
            "required_entity_ids":   [e["entity_id"] for e in sorted_entities],
            "path_steps":            [s.dict() for s in path_steps],
            "is_truncated":          is_truncated,
            "total_steps":           len(all_steps),
        }

    async def _compute_chapter_path(self, user_id: str, topic_key: str, blueprint_id: str) -> dict:
        """基于已发布蓝图，返回 chapter 级学习路径。"""
        # 获取所有章节
        chapters_result = await self.db.execute(
            text("""
                SELECT sc.chapter_id::text, sc.title, sc.objective,
                       sc.chapter_order, ss.stage_id::text, ss.title AS stage_title,
                       ss.stage_order
                FROM skill_chapters sc
                JOIN skill_stages ss ON ss.stage_id = sc.stage_id
                WHERE sc.blueprint_id = CAST(:bid AS uuid)
                ORDER BY ss.stage_order, sc.chapter_order
            """),
            {"bid": blueprint_id}
        )
        chapters = [dict(r._mapping) for r in chapters_result.fetchall()]

        if not chapters:
            return {
                "user_id": user_id, "topic_key": topic_key,
                "path_type": "chapter", "path_steps": [],
                "is_truncated": False, "total_steps": 0,
            }

        # 获取用户已完成章节（tutorial_id 是 varchar，blueprint_id 是 uuid，需显式转 text 比较）
        progress_result = await self.db.execute(
            text("""
                SELECT chapter_id::text FROM chapter_progress
                WHERE user_id = CAST(:uid AS uuid)
                  AND tutorial_id IN (
                    SELECT blueprint_id::text FROM skill_blueprints
                    WHERE topic_key = :tk
                  )
                  AND completed = true
            """),
            {"uid": user_id, "tk": topic_key}
        )
        completed_ids = {r[0] for r in progress_result.fetchall()}

        # 计算每章的知识点掌握缺口分
        mastery_svc = MasteryStateService(self.db)
        mastered = await mastery_svc.get_mastered_entities(user_id, threshold=0.7)
        mastered_ids = {m["entity_id"] for m in mastered}

        entity_links_result = await self.db.execute(
            text("""
                SELECT chapter_id::text, entity_id::text
                FROM chapter_entity_links
                WHERE chapter_id IN (
                    SELECT chapter_id FROM skill_chapters
                    WHERE blueprint_id = CAST(:bid AS uuid)
                )
            """),
            {"bid": blueprint_id}
        )
        chapter_entities: dict[str, list[str]] = {}
        for r in entity_links_result.fetchall():
            chapter_entities.setdefault(r[0], []).append(r[1])

        # 构建完整路径步骤（保留全部章节；已完成的打标记，不过滤）
        steps = []
        for ch in chapters:
            entities = chapter_entities.get(ch["chapter_id"], [])
            gap_score = (
                len([e for e in entities if e not in mastered_ids]) / len(entities)
                if entities else 0.5
            )
            steps.append({
                "type":              "chapter",
                "chapter_id":        ch["chapter_id"],
                "title":             ch["title"],
                "stage_title":       ch["stage_title"],
                "objective":         ch.get("objective", ""),
                "estimated_minutes": 30,
                "gap_score":         round(gap_score, 2),
                "completed":         ch["chapter_id"] in completed_ids,
            })

        # 不截断：用户有权看到完整学习路径
        completed_cnt = sum(1 for s in steps if s["completed"])
        return {
            "user_id":       user_id,
            "topic_key":     topic_key,
            "path_type":     "chapter",
            "path_steps":    steps,
            "is_truncated":  False,
            "total_steps":   len(steps),
            "completed_cnt": completed_cnt,
        }

    @staticmethod
    def _compute_depths(entities: list[dict], relations: list[dict]) -> dict[str, int]:
        """计算每个实体在依赖图中的拓扑深度（BFS from roots）。"""
        adj: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {e["entity_id"]: 0 for e in entities}
        for r in relations:
            if r["relation_type"] == "prerequisite_of":
                adj[r["source_entity_id"]].append(r["target_entity_id"])
                in_degree[r["target_entity_id"]] += 1

        depths: dict[str, int] = {}
        queue  = deque(
            (eid, 0) for eid, deg in in_degree.items() if deg == 0
        )
        while queue:
            eid, depth = queue.popleft()
            depths[eid] = depth
            for neighbor in adj[eid]:
                queue.append((neighbor, depth + 1))
        return depths
