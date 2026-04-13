"""
apps/api/tasks/embedding_tasks.py
Phase 1：知识实体 embedding 批量回填管线

提供两个 Celery 任务（都跑在 knowledge 队列）：

1. embed_single_entity(entity_id)
   单条任务，由审核 hook 触发。审核通过即插入向量，无需等批量。

2. backfill_entity_embeddings(space_id=None, batch_size=32)
   批量任务。扫 review_status='approved' AND embedding IS NULL 的实体，
   按 batch_size 分批调用 LLMGateway.embed()，逐批 commit。
   space_id=None 表示全库回填。

设计要点：
  - 文本拼接：canonical_name + " — " + (short_definition or "")，截断到 512 字符
  - 跳过空内容：name 为空或拼接后没有任何信号的实体
  - 失败容错：单条 embedding 返回空向量时跳过该条，不阻断整批
  - 任务级幂等：每次都查 IS NULL 才处理，重跑无副作用
  - 写入用 CAST(:emb AS vector) 让 asyncpg 接受 Python list
"""
from __future__ import annotations

import asyncio

import structlog
from celery import signals as celery_signals  # noqa: F401  (保持与其他任务文件一致)

from apps.api.tasks.tutorial_tasks import celery_app   # 复用同一 Celery 实例

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# 任务 1：单条 embedding（由审核 hook 触发）
# ════════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="apps.api.tasks.embedding_tasks.embed_single_entity",
)
def embed_single_entity(self, entity_id: str):
    """
    给单个实体生成 embedding 并写库。
    由 entity 被 approved 的 hook 触发（人工审核 + 自动审核 + 批量审核）。
    """
    logger.info("embed_single_entity start", entity_id=entity_id)
    try:
        asyncio.run(_embed_single_async(entity_id))
        logger.info("embed_single_entity done", entity_id=entity_id)
    except Exception as exc:
        logger.error("embed_single_entity failed", entity_id=entity_id, error=str(exc))
        raise self.retry(exc=exc)


async def _embed_single_async(entity_id: str) -> None:
    from sqlalchemy import text
    from apps.api.core.db import async_session_factory, engine
    from apps.api.core.llm_gateway import get_llm_gateway

    # FIX-1：worker fork 后丢弃旧连接句柄
    engine.sync_engine.dispose(close=False)

    async with async_session_factory() as session:
        # 读实体
        row = await session.execute(
            text("""
                SELECT entity_id::text, canonical_name, short_definition, embedding IS NULL AS is_null
                FROM knowledge_entities
                WHERE entity_id = CAST(:eid AS uuid)
                  AND review_status = 'approved'
            """),
            {"eid": entity_id},
        )
        r = row.fetchone()
        if not r:
            logger.warning("entity not found or not approved", entity_id=entity_id)
            return
        if not r.is_null:
            logger.info("entity already has embedding, skip", entity_id=entity_id)
            return

        text_for_embed = _build_embed_text(r.canonical_name, r.short_definition)
        if not text_for_embed:
            logger.warning("entity has empty name+definition, skip", entity_id=entity_id)
            return

        gw = get_llm_gateway()
        vec = await gw.embed_single(text_for_embed)
        if not vec:
            logger.warning("embedding returned empty vector, skip",
                           entity_id=entity_id, text=text_for_embed[:80])
            return

        await session.execute(
            text("""
                UPDATE knowledge_entities
                SET embedding = CAST(:emb AS vector),
                    updated_at = NOW()
                WHERE entity_id = CAST(:eid AS uuid)
                  AND embedding IS NULL
            """),
            {"eid": entity_id, "emb": str(vec)},
        )
        await session.commit()


# ════════════════════════════════════════════════════════════════
# 任务 2：批量回填（管理员手动触发）
# ════════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    max_retries=1,
    default_retry_delay=30,
    name="apps.api.tasks.embedding_tasks.backfill_entity_embeddings",
)
def backfill_entity_embeddings(self, space_id: str | None = None, batch_size: int = 32):
    """
    扫一遍 approved AND embedding IS NULL 的实体，按 batch 调用 embed() 灌满。
    space_id=None：全库扫描
    space_id="xxx-uuid"：限定单个 knowledge_space

    返回值：dict 带 processed/skipped/total
    """
    logger.warning("backfill_entity_embeddings start",
                   space_id=space_id, batch_size=batch_size)
    try:
        result = asyncio.run(_backfill_async(space_id, batch_size))
        logger.warning("backfill_entity_embeddings done", **result)
        return result
    except Exception as exc:
        logger.error("backfill_entity_embeddings failed", error=str(exc))
        raise self.retry(exc=exc)


async def _backfill_async(space_id: str | None, batch_size: int) -> dict:
    from sqlalchemy import text
    from apps.api.core.db import async_session_factory, engine
    from apps.api.core.llm_gateway import get_llm_gateway

    engine.sync_engine.dispose(close=False)
    gw = get_llm_gateway()

    processed = 0
    skipped_empty = 0
    skipped_failed = 0
    total_seen = 0

    async with async_session_factory() as session:
        # 统计待处理总数
        if space_id:
            count_sql = text("""
                SELECT count(*) FROM knowledge_entities
                WHERE review_status = 'approved' AND embedding IS NULL
                  AND space_id = CAST(:sid AS uuid)
            """)
            count_params = {"sid": space_id}
        else:
            count_sql = text("""
                SELECT count(*) FROM knowledge_entities
                WHERE review_status = 'approved' AND embedding IS NULL
            """)
            count_params = {}
        total = (await session.execute(count_sql, count_params)).scalar_one()
        logger.warning("backfill scan done", total_to_process=total, space_id=space_id)

        if total == 0:
            return {"processed": 0, "skipped_empty": 0, "skipped_failed": 0, "total": 0}

        # 分批取
        offset = 0
        while True:
            if space_id:
                fetch_sql = text("""
                    SELECT entity_id::text, canonical_name, short_definition
                    FROM knowledge_entities
                    WHERE review_status = 'approved' AND embedding IS NULL
                      AND space_id = CAST(:sid AS uuid)
                    ORDER BY entity_id
                    LIMIT :lim
                """)
                fetch_params = {"sid": space_id, "lim": batch_size}
            else:
                fetch_sql = text("""
                    SELECT entity_id::text, canonical_name, short_definition
                    FROM knowledge_entities
                    WHERE review_status = 'approved' AND embedding IS NULL
                    ORDER BY entity_id
                    LIMIT :lim
                """)
                fetch_params = {"lim": batch_size}

            rows = (await session.execute(fetch_sql, fetch_params)).fetchall()
            if not rows:
                break
            total_seen += len(rows)

            # 拼文本，过滤空的
            payload = []
            for r in rows:
                txt = _build_embed_text(r.canonical_name, r.short_definition)
                if txt:
                    payload.append((r.entity_id, txt))
                else:
                    skipped_empty += 1

            if not payload:
                # 这批全是空文本，跳到下一页（用 OFFSET 防止死循环）
                # 但因为我们的 WHERE 是 IS NULL，跳过的实体下次还会被选中
                # 解决：把空 name 的实体直接打个标记或者直接退出
                # 简单办法：直接退出，让人工修
                logger.warning("batch all empty, aborting backfill",
                               sample_ids=[r.entity_id for r in rows[:3]])
                break

            texts = [p[1] for p in payload]
            try:
                vectors = await gw.embed(texts)
            except Exception as e:
                logger.error("embed batch failed", error=str(e), batch_size=len(texts))
                skipped_failed += len(texts)
                # 跳过这批（这些实体下次重试会再被选中）
                # 为了避免死循环，break
                break

            # 写库
            for (eid, _txt), vec in zip(payload, vectors):
                if not vec:
                    skipped_failed += 1
                    continue
                await session.execute(
                    text("""
                        UPDATE knowledge_entities
                        SET embedding = CAST(:emb AS vector),
                            updated_at = NOW()
                        WHERE entity_id = CAST(:eid AS uuid)
                          AND embedding IS NULL
                    """),
                    {"eid": eid, "emb": str(vec)},
                )
                processed += 1

            await session.commit()
            logger.info("batch committed",
                        batch_processed=len(payload),
                        cumulative_processed=processed,
                        cumulative_total=total_seen)

            # 如果这批拿到的 < batch_size，说明扫完了
            if len(rows) < batch_size:
                break

    return {
        "processed":     processed,
        "skipped_empty": skipped_empty,
        "skipped_failed": skipped_failed,
        "total":         total_seen,
    }


# ════════════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════════════

def _build_embed_text(name: str | None, short_def: str | None) -> str:
    """
    生成用于 embedding 的文本。
    - 仅用 canonical_name + short_definition（bge-m3 对短文本召回质量更高）
    - 截断到 512 字符
    - 全空返回空串（调用方据此跳过）
    """
    name = (name or "").strip()
    sdef = (short_def or "").strip()
    if not name and not sdef:
        return ""
    if not sdef:
        return name[:512]
    if not name:
        return sdef[:512]
    combined = f"{name} — {sdef}"
    return combined[:512]
