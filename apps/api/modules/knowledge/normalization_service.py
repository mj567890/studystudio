"""
apps/api/modules/knowledge/normalization_service.py
Block B：知识归一化服务

三层归一策略：
  第一层：精确匹配自动合并
  第二层：模糊匹配（同层阈值 0.94）→ 推送审核队列
  第三层：强制隔离（同名异型/异域）
跨层去重（跨层阈值 0.88）：个人层候选与上层比对
"""
import uuid
from math import sqrt

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import CONFIG
from apps.api.core.llm_gateway import get_llm_gateway

logger = structlog.get_logger(__name__)

CROSS_LAYER_THRESHOLD = CONFIG.normalization.cross_layer_threshold  # 0.88
SAME_LAYER_THRESHOLD  = CONFIG.normalization.same_layer_threshold   # 0.94
EDIT_DIST_MAX         = CONFIG.normalization.edit_distance_max      # 3


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot   = sum(a * b for a, b in zip(v1, v2))
    norm1 = sqrt(sum(a * a for a in v1))
    norm2 = sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def edit_distance(s1: str, s2: str) -> int:
    """Levenshtein 编辑距离。"""
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i
    for j in range(n + 1): dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = (dp[i-1][j-1] if s1[i-1] == s2[j-1]
                        else 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]))
    return dp[m][n]


class EntityNormalizationService:
    """对候选实体进行归一化，写入正式知识表或审核队列。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db  = db
        self.llm = get_llm_gateway()

    async def normalize_batch(
        self,
        candidates: list[dict],
        document_id: str,
    ) -> dict[str, int]:
        """
        批量归一化候选实体。
        返回统计：{"merged": int, "created": int, "audited": int, "referenced": int}
        """
        stats = {"merged": 0, "created": 0, "audited": 0, "referenced": 0}

        # 为所有候选生成向量（批量）
        names = [c["canonical_name"] if "canonical_name" in c else c["name"] for c in candidates]
        embeddings = await self.llm.embed(names)
        for candidate, emb in zip(candidates, embeddings):
            candidate["_embedding"] = emb
            if "canonical_name" not in candidate:
                candidate["canonical_name"] = candidate["name"]

        for candidate in candidates:
            result = await self._normalize_one(candidate, document_id)
            stats[result] += 1

        await self.db.commit()
        logger.info("Normalization batch complete", document_id=document_id, stats=stats)
        return stats

    async def _normalize_one(self, candidate: dict, document_id: str) -> str:
        """
        归一化单个候选实体。
        返回操作类型：merged / created / audited / referenced
        """
        space_type = candidate.get("space_type", "global")
        domain_tag = candidate.get("domain_tag", "")
        canon_name = candidate["canonical_name"]
        entity_type = candidate.get("entity_type", "concept")
        emb = candidate["_embedding"]

        # ── 第三层：强制隔离检查（同名异型 / 异域 → 不合并）────────────────
        isolation_check = await self.db.execute(
            text("""
                SELECT entity_id, entity_type, domain_tag FROM knowledge_entities
                WHERE canonical_name = :name
                  AND review_status = 'approved'
                  AND (entity_type != :etype OR domain_tag != :domain)
                LIMIT 1
            """),
            {"name": canon_name, "etype": entity_type, "domain": domain_tag}
        )
        if isolation_check.fetchone():
            # 强制隔离：只建立 related 关系，不合并
            await self._create_entity(candidate)
            return "created"

        # ── 第一层：精确匹配自动合并 ──────────────────────────────────────
        exact_match = await self.db.execute(
            text("""
                SELECT entity_id FROM knowledge_entities
                WHERE canonical_name = :name
                  AND domain_tag = :domain
                  AND space_type = :space
                  AND review_status = 'approved'
                LIMIT 1
            """),
            {"name": canon_name, "domain": domain_tag, "space": space_type}
        )
        if exact_match.fetchone():
            # 已存在精确匹配，跳过（幂等）
            return "merged"

        # ── 跨层去重（个人层候选与全局/课程层比对）──────────────────────
        if space_type == "personal":
            upper_match = await self._find_upper_layer_match(emb, domain_tag, canon_name)
            if upper_match and upper_match["similarity"] > CROSS_LAYER_THRESHOLD:
                # 不创建新实体，创建引用记录
                await self.db.execute(
                    text("""
                        INSERT INTO personal_entity_references
                          (id, user_id, ref_entity_id, source_doc_id, candidate_snapshot)
                        VALUES
                          (:id, :user_id, :ref_id, :doc_id, CAST(:snapshot AS jsonb))
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id":       str(uuid.uuid4()),
                        "user_id":  candidate.get("owner_id"),
                        "ref_id":   upper_match["entity_id"],
                        "doc_id":   document_id,
                        "snapshot": __import__("json").dumps(
                            {k: v for k, v in candidate.items() if not k.startswith("_")}
                        ),
                    }
                )
                return "referenced"

        # ── 第二层：模糊匹配（同层，SAME_LAYER_THRESHOLD=0.94）───────────
        similar = await self._find_similar_same_layer(emb, domain_tag, space_type, canon_name)
        if similar and similar["similarity"] > SAME_LAYER_THRESHOLD:
            # 推入审核队列，人工决策是否合并
            await self.db.execute(
                text("""
                    INSERT INTO entity_normalize_audit
                      (audit_id, candidate_id, similar_entity_id, similarity_score)
                    VALUES (:id, :cid, :sid, :score)
                """),
                {
                    "id":    str(uuid.uuid4()),
                    "cid":   candidate.get("entity_id", str(uuid.uuid4())),
                    "sid":   similar["entity_id"],
                    "score": similar["similarity"],
                }
            )
            return "audited"

        # 不匹配任何已有实体，创建新实体
        await self._create_entity(candidate)
        return "created"

    async def _create_entity(self, candidate: dict) -> str:
        """将候选实体写入正式知识表（pending 状态，等待审核）。"""
        entity_id = candidate.get("entity_id") or str(uuid.uuid4())
        await self.db.execute(
            text("""
                INSERT INTO knowledge_entities
                  (entity_id, name, entity_type, canonical_name, domain_tag,
                   space_type, space_id, owner_id, visibility,
                   short_definition, detailed_explanation, review_status)
                VALUES
                  (:entity_id, :name, :entity_type, :canonical_name, :domain_tag,
                   :space_type, :space_id, :owner_id, :visibility,
                   :short_def, :detailed_exp, 'pending')
                ON CONFLICT DO NOTHING
            """),
            {
                "entity_id":    entity_id,
                "name":         candidate.get("name", candidate["canonical_name"]),
                "entity_type":  candidate.get("entity_type", "concept"),
                "canonical_name": candidate["canonical_name"],
                "domain_tag":   candidate.get("domain_tag", "general"),
                "space_type":   candidate.get("space_type", "global"),
                "space_id":     candidate.get("space_id"),
                "owner_id":     candidate.get("owner_id"),
                "visibility":   candidate.get("visibility", "public"),
                "short_def":    candidate.get("short_definition", ""),
                "detailed_exp": candidate.get("detailed_explanation", ""),
            }
        )
        return entity_id

    async def _find_upper_layer_match(
        self, embedding: list[float], domain_tag: str, name: str
    ) -> dict | None:
        """在全局层和课程层中查找相似实体。"""
        rows = await self.db.execute(
            text("""
                SELECT entity_id, canonical_name, embedding
                FROM knowledge_entities
                WHERE space_type IN ('global','course')
                  AND domain_tag = :domain
                  AND review_status = 'approved'
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT 5
            """),
            {"domain": domain_tag, "emb": str(embedding)}
        )
        return self._best_match(rows.fetchall(), embedding, name)

    async def _find_similar_same_layer(
        self, embedding: list[float], domain_tag: str, space_type: str, name: str
    ) -> dict | None:
        """在同层中查找相似实体（向量 + 编辑距离双重过滤）。"""
        rows = await self.db.execute(
            text("""
                SELECT entity_id, canonical_name, embedding
                FROM knowledge_entities
                WHERE space_type = :space
                  AND domain_tag = :domain
                  AND review_status = 'approved'
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT 5
            """),
            {"space": space_type, "domain": domain_tag, "emb": str(embedding)}
        )
        return self._best_match(rows.fetchall(), embedding, name)

    def _best_match(self, rows, embedding: list[float], name: str) -> dict | None:
        """从候选行中找最佳匹配（向量相似度 + 编辑距离）。"""
        best = None
        for row in rows:
            if row.embedding is None:
                continue
            sim  = cosine_similarity(embedding, list(row.embedding))
            dist = edit_distance(name, row.canonical_name)
            if dist <= EDIT_DIST_MAX and (best is None or sim > best["similarity"]):
                best = {"entity_id": str(row.entity_id),
                        "canonical_name": row.canonical_name,
                        "similarity": sim}
        return best
