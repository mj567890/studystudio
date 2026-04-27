"""
apps/api/tasks/auto_review_tasks.py
AI 两轮全自动审核 (G-2)

轮次策略：
  第一轮  confidence >= 0.75 + approve  → approved
          decision == reject            → rejected
          其余                          → 进入第二轮

  第二轮  换更严格 prompt 重审灰区实体
          confidence >= 0.60            → approved
          其余                          → rejected（彻底清零 pending）

审核完成后自动将 document 状态推进到 reviewed。
"""
from __future__ import annotations
import asyncio, json, re
import structlog
from apps.api.tasks.tutorial_tasks import celery_app
from apps.api.tasks.task_tracker import task_tracker

logger = structlog.get_logger()

# ── 第一轮 prompt ─────────────────────────────────────────────
ROUND1_PROMPT = """你是知识点质量审核专家。请对以下知识点逐一判断是否有独立学习价值。

判断规则：
- reject：人名、账号名、密码、手机号、邮箱、文件路径、随机字符串、残句碎片
- approve：领域标准术语、明确技术概念、可复用流程名、典型攻击/防护方式
- uncertain：有一定价值但定义不够清晰，或同名多义词

知识点列表（JSON）：
{entities_json}

严格按 JSON 数组输出，不含其他内容：
[{{"entity_id":"...","decision":"approve|reject|uncertain","confidence":0.95,"reason":"10字以内"}}]"""

# ── 第二轮 prompt（专门处理灰区）────────────────────────────────
ROUND2_PROMPT = """你是知识点质量严格审核专家。以下知识点已被初审标记为「不确定」，请再次严格判断。

要求：
- 只要有一定领域学习价值，就输出 approve（放宽标准，避免漏判）
- 确实是噪声、碎片或无法单独解释的词，才输出 reject
- 不允许再次输出 uncertain，必须给出明确结论

知识点列表（JSON）：
{entities_json}

严格按 JSON 数组输出，不含其他内容：
[{{"entity_id":"...","decision":"approve|reject","confidence":0.90,"reason":"10字以内"}}]"""


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=600,   # 10分钟：审核所有 pending 实体（可能数百条 × 批量 LLM）
    time_limit=720,        # 12分钟：硬杀
    on_failure=task_tracker.on_failure,
    on_success=task_tracker.on_success,
)
def auto_review_entities(self, space_id: str):
    """对指定 space 下所有 pending 知识点执行两轮全自动审核。"""
    logger.info("auto_review start", space_id=space_id)
    try:
        asyncio.run(_auto_review_async(space_id))
    except Exception as exc:
        logger.error("auto_review failed", space_id=space_id, error=str(exc))
        raise self.retry(exc=exc)


def _make_session():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool
    import os
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool, connect_args={"timeout": 5})
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _acquire_review_lock(SF, space_id: str) -> bool:
    """原子获取 space 级审核锁，使用 PostgreSQL advisory lock 防并行。"""
    from sqlalchemy import text
    # 将 UUID 转为整数用于 advisory lock
    lock_id = hash(space_id) & 0x7FFFFFFF  # 32-bit signed int
    async with SF() as session:
        result = await session.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id}
        )
        acquired = result.scalar()
        if acquired:
            logger.info("Review lock acquired", space_id=space_id, lock_id=lock_id)
        return acquired


async def _release_review_lock(SF, space_id: str) -> None:
    """释放 space 级审核锁。"""
    from sqlalchemy import text
    lock_id = hash(space_id) & 0x7FFFFFFF
    try:
        async with SF() as session:
            await session.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id}
            )
            await session.commit()
        logger.info("Review lock released", space_id=space_id, lock_id=lock_id)
    except Exception as e:
        logger.warning("Failed to release review lock", space_id=space_id, error=str(e))


async def _auto_review_async(space_id: str) -> None:
    from apps.api.core.llm_gateway import get_llm_gateway
    from sqlalchemy import text

    llm = get_llm_gateway()
    SF  = _make_session()

    # ── 空间级审核锁：原子声明正在审核，防止 resume 并行派发 ──────
    lock_acquired = await _acquire_review_lock(SF, space_id)
    if not lock_acquired:
        logger.info("Review lock not acquired, another review is active", space_id=space_id)
        return

    try:
        # ── 读取 pending 实体 ────────────────────────────────────────
        async with SF() as session:
            result = await session.execute(
                text("""
                    SELECT entity_id::text, canonical_name, entity_type,
                           short_definition, domain_tag
                    FROM knowledge_entities
                    WHERE space_id = CAST(:sid AS uuid)
                      AND review_status = 'pending'
                    ORDER BY created_at
                    LIMIT 100
                """),
                {"sid": space_id}
            )
            entities = [dict(r._mapping) for r in result.fetchall()]

        if not entities:
            logger.info("No pending entities", space_id=space_id)
            await _finalize_documents(space_id)
            return

        logger.info("Reviewing entities", count=len(entities), space_id=space_id)

        # ── 第一轮审核 ───────────────────────────────────────────────
        approved_ids:   list[str] = []
        rejected_ids:   list[str] = []
        uncertain_batch: list[dict] = []

        for i in range(0, len(entities), 5):
            batch = entities[i:i+5]
            decisions = await _call_llm(llm, ROUND1_PROMPT, batch)
            if not decisions:
                # LLM 调用失败：整批保持 pending，等下次重试
                logger.warning("Round1 LLM failed for batch, entities stay pending",
                               count=len(batch), space_id=space_id)
                continue
            for d in decisions:
                eid = d.get("entity_id", "")
                dec = d.get("decision", "uncertain")
                conf = float(d.get("confidence", 0))
                if dec == "reject":
                    rejected_ids.append(eid)
                elif dec == "approve" and conf >= 0.75:
                    approved_ids.append(eid)
                else:
                    # uncertain 或低置信度 approve → 进第二轮
                    uncertain_batch.append(next(
                        (e for e in batch if e["entity_id"] == eid), {"entity_id": eid}
                    ))

        logger.info("Round1 done",
                    approved=len(approved_ids), rejected=len(rejected_ids),
                    uncertain=len(uncertain_batch))

        # ── 第二轮审核（灰区）────────────────────────────────────────
        if uncertain_batch:
            for i in range(0, len(uncertain_batch), 5):
                batch2 = uncertain_batch[i:i+5]
                decisions2 = await _call_llm(llm, ROUND2_PROMPT, batch2)
                if not decisions2:
                    # LLM 失败：这批 uncertain 全部 reject 兜底，避免永久 pending
                    logger.warning("Round2 LLM failed, rejecting uncertain batch as fallback",
                                   count=len(batch2), space_id=space_id)
                    for e in batch2:
                        rejected_ids.append(e["entity_id"])
                    continue
                for d in decisions2:
                    eid = d.get("entity_id", "")
                    dec = d.get("decision", "reject")
                    conf = float(d.get("confidence", 0))
                    if dec == "approve" and conf >= 0.60:
                        approved_ids.append(eid)
                    else:
                        rejected_ids.append(eid)
            # 仍未匹配到决策的 uncertain 实体，全部 reject（清零 pending）
            decided = set(approved_ids) | set(rejected_ids)
            for e in uncertain_batch:
                if e["entity_id"] not in decided:
                    rejected_ids.append(e["entity_id"])

        logger.info("Round2 done",
                    total_approved=len(approved_ids), total_rejected=len(rejected_ids))

        # ── 批量写入结果 ─────────────────────────────────────────────
        SF2 = _make_session()
        async with SF2() as session:
            async with session.begin():
                if approved_ids:
                    await session.execute(
                        text("""
                            UPDATE knowledge_entities
                            SET review_status='approved', updated_at=now()
                            WHERE entity_id = ANY(CAST(:ids AS uuid[]))
                              AND review_status='pending'
                        """),
                        {"ids": approved_ids}
                    )
                if rejected_ids:
                    await session.execute(
                        text("""
                            UPDATE knowledge_entities
                            SET review_status='rejected', updated_at=now()
                            WHERE entity_id = ANY(CAST(:ids AS uuid[]))
                              AND review_status='pending'
                        """),
                        {"ids": rejected_ids}
                    )

        # ── Phase 1 hook: 批量派发 embedding 任务 ──
        if approved_ids:
            try:
                from apps.api.tasks.embedding_tasks import backfill_entity_embeddings
                backfill_entity_embeddings.apply_async(
                    args=[space_id, 32],
                    queue="knowledge",
                )
                logger.info("batch embedding task dispatched after auto_review",
                            count=len(approved_ids))
            except Exception as _e:
                logger.warning("Failed to dispatch batch embedding, falling back to per-entity",
                               error=str(_e), count=len(approved_ids))
                from apps.api.tasks.embedding_tasks import embed_single_entity
                for eid in approved_ids:
                    embed_single_entity.apply_async(args=[eid], queue="knowledge")

        # ── 真实检查：还有 pending 则继续，否则推进文档 ───────────────
        async with SF() as session:
            remaining = await session.execute(
                text("""
                    SELECT COUNT(*) FROM knowledge_entities
                    WHERE space_id = CAST(:sid AS uuid)
                      AND review_status = 'pending'
                """),
                {"sid": space_id}
            )
            pending_count = remaining.scalar() or 0

        if pending_count > 0:
            logger.info("More pending entities remain, chaining next review",
                        space_id=space_id, remaining=pending_count)
            auto_review_entities.apply_async(
                args=[space_id], queue="knowledge.review", countdown=5
            )
        else:
            logger.info("All entities reviewed, finalizing documents", space_id=space_id)
            await _finalize_documents(space_id)
    finally:
        await _release_review_lock(SF, space_id)


async def _finalize_documents(space_id: str) -> None:
    """审核完成后：验证无 pending → 推进文档到 embedding + 派发 embed 任务。

    Blueprint 不再在此触发，改由 embedding 完成后触发，
    确保 V2 blueprint（依赖 embedding）不会因时序问题失败。
    """
    from sqlalchemy import text
    SF = _make_session()

    # 0. 防御：再次确认没有 pending 实体，防止过早推进
    async with SF() as session:
        remaining = await session.execute(
            text("""
                SELECT COUNT(*) FROM knowledge_entities
                WHERE space_id = CAST(:sid AS uuid)
                  AND review_status = 'pending'
            """),
            {"sid": space_id}
        )
        if (remaining.scalar() or 0) > 0:
            logger.warning("Skipping finalize — pending entities still exist",
                          space_id=space_id, count=remaining.scalar())
            return

    # 1. 推进文档状态：extracted → embedding
    async with SF() as session:
        async with session.begin():
            result = await session.execute(
                text("""
                    UPDATE documents
                    SET document_status = 'embedding', updated_at = now()
                    WHERE space_id = CAST(:sid AS uuid)
                      AND document_status = 'extracted'
                    RETURNING document_id::text
                """),
                {"sid": space_id}
            )
            promoted = result.fetchall()
    if promoted:
        logger.info("Documents advanced to embedding",
                    space_id=space_id, count=len(promoted))
    else:
        logger.info("No documents to advance (already past extracted)",
                    space_id=space_id)


async def _call_llm(llm, prompt_tpl: str, batch: list[dict]) -> list[dict]:
    """调用 LLM 审核一批实体，失败返回空列表。"""
    entities_json = json.dumps(
        [{"entity_id": e["entity_id"],
          "name": e.get("canonical_name", ""),
          "type": e.get("entity_type", ""),
          "definition": (e.get("short_definition") or "")[:100]}
         for e in batch],
        ensure_ascii=False
    )
    try:
        raw = await asyncio.wait_for(
            llm.generate(prompt_tpl.format(entities_json=entities_json),
                         model_route="knowledge_extraction"),
            timeout=120
        )
        return _parse_json_array(raw)
    except Exception as e:
        logger.warning("LLM call failed", error=str(e))
        return []


def _parse_json_array(raw: str) -> list:
    clean = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return []


# ── 定时巡检：自动续接中断的审核任务（resume_pending_review_v1）────────
@celery_app.task(name="apps.api.tasks.auto_review_tasks.resume_pending_review",
               bind=True, on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def resume_pending_review(self) -> None:
    """
    每 5 分钟由 celery_beat 触发。
    检查所有有 pending 实体的 space，自动派发 auto_review_entities。
    解决任务链因 worker 重启而中断的问题。
    发现卡住任务会写入 task_executions 表，供管理页面查看。
    """
    import asyncio as _asyncio
    from sqlalchemy import text as _text
    import json as _json, uuid as _uuid

    async def _check() -> None:
        # resume_blueprint_check_v1
        SF = _make_session()
        async with SF() as session:
            recovered_actions: list[str] = []
            stuck_bp_count = 0
            stuck_doc_count = 0
            # 1. 续接审核
            result = await session.execute(
                _text("""
                    SELECT DISTINCT space_id::text
                    FROM knowledge_entities
                    WHERE review_status = 'pending'
                """)
            )
            space_ids = [r[0] for r in result.fetchall()]

            # 2. 检查已审核完但没有 blueprint 的 space
            result2 = await session.execute(
                _text("""
                    SELECT ks.space_id::text, ks.name
                    FROM knowledge_spaces ks
                    WHERE EXISTS (
                        SELECT 1 FROM knowledge_entities ke
                        WHERE ke.space_id = ks.space_id
                          AND ke.review_status = 'approved'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM knowledge_entities ke2
                        WHERE ke2.space_id = ks.space_id
                          AND ke2.review_status = 'pending'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM skill_blueprints sb
                        WHERE sb.space_id = ks.space_id
                          AND (
                              sb.status = 'published'
                              OR (sb.status = 'generating'
                                  AND sb.updated_at > now() - interval '2 hours')
                          )
                    )
                    AND EXISTS (
                        SELECT 1 FROM documents d
                        WHERE d.space_id = ks.space_id
                          AND d.document_status IN ('reviewed', 'published', 'embedding')
                    )
                """)
            )
            missing_blueprints = [dict(r._mapping) for r in result2.fetchall()]

            # 3. 安全网：检查 parsed 状态但实体为空的文档（reparse 后未触发提取）
            result3 = await session.execute(
                _text("""
                    SELECT d.document_id::text, d.space_type, d.space_id::text
                    FROM documents d
                    WHERE d.document_status = 'parsed'
                      AND d.chunk_count > 0
                      AND NOT EXISTS (
                          SELECT 1 FROM knowledge_entities ke
                          WHERE ke.space_id = d.space_id
                            AND ke.review_status = 'pending'
                      )
                """)
            )
            stuck_docs = [dict(r._mapping) for r in result3.fetchall()]

        for sid in space_ids:
            auto_review_entities.apply_async(args=[sid], queue="knowledge.review")
            logger.info("resume_pending_review: triggered review", space_id=sid)

        # resume_blueprint_rescue_v1：重置卡死的 generating（超时2小时）
        # 注意：此处必须新开 session，上方 async with 块已关闭
        async with SF() as rescue_session:
            result_stuck = await rescue_session.execute(
                _text("""
                    UPDATE skill_blueprints
                    SET status = 'draft', updated_at = now()
                    WHERE status = 'generating'
                      AND updated_at < now() - interval '2 hours'
                    RETURNING space_id::text, topic_key
                """)
            )
            stuck_rows = result_stuck.fetchall()
            await rescue_session.commit()
        if stuck_rows:
            logger.warning(
                "resume_pending_review: reset stuck generating blueprints",
                count=len(stuck_rows),
                spaces=[r[0] for r in stuck_rows],
            )

        for row in missing_blueprints:
            try:
                from apps.api.tasks.blueprint_tasks import synthesize_blueprint
                synthesize_blueprint.apply_async(
                    args=[row["name"], row["space_id"]], queue="knowledge"
                )
                logger.info("resume_pending_review: triggered blueprint",
                            space_id=row["space_id"], topic_key=row["name"])
            except Exception as e:
                logger.warning("resume_pending_review: blueprint trigger failed", error=str(e))

        for doc in stuck_docs:
            try:
                from apps.api.tasks.knowledge_tasks import run_extraction
                run_extraction.apply_async(
                    args=[doc["document_id"], doc["space_type"], doc["space_id"]],
                    queue="knowledge",
                )
                logger.info("resume_pending_review: triggered extraction for stuck doc",
                            document_id=doc["document_id"])
            except Exception as e:
                logger.warning("resume_pending_review: extraction trigger failed", error=str(e))

        # Phase 5: LLM 恢复感知 —— 自动重试因 LLM 连接问题而 failed 的文档
        async with SF() as recovery_session:
            recovery_result = await recovery_session.execute(
                _text("""
                    SELECT d.document_id::text, d.space_type, d.space_id::text
                    FROM documents d
                    WHERE d.document_status = 'failed'
                      AND d.updated_at > now() - INTERVAL '1 hour'
                      AND (d.last_error LIKE '%Connection%'
                           OR d.last_error LIKE '%Timeout%'
                           OR d.last_error LIKE '%unreachable%'
                           OR d.last_error LIKE '%error%')
                    ORDER BY d.updated_at DESC
                    LIMIT 20
                """)
            )
            recoverable_docs = [dict(r._mapping) for r in recovery_result.fetchall()]

        for doc in recoverable_docs:
            try:
                await recovery_session.execute(
                    _text("UPDATE documents SET document_status='parsed', updated_at=NOW() "
                          "WHERE document_id=CAST(:did AS uuid)"),
                    {"did": doc["document_id"]}
                )
                await recovery_session.commit()
                from apps.api.tasks.knowledge_tasks import run_extraction
                run_extraction.apply_async(
                    args=[doc["document_id"], doc["space_type"] or "global", doc["space_id"]],
                    queue="knowledge",
                )
                logger.info("resume_pending_review: LLM recovery auto-retry",
                            document_id=doc["document_id"])
            except Exception as e:
                logger.warning("resume_pending_review: LLM recovery retry failed",
                               document_id=doc["document_id"], error=str(e))

        if space_ids:
            logger.info("resume_pending_review: dispatched reviews", count=len(space_ids))
        elif missing_blueprints:
            logger.info("resume_pending_review: dispatched blueprints", count=len(missing_blueprints))
        elif stuck_docs:
            logger.info("resume_pending_review: rescued stuck docs", count=len(stuck_docs))
        elif recoverable_docs:
            logger.info("resume_pending_review: LLM recovery retries", count=len(recoverable_docs))
        else:
            logger.info("resume_pending_review: all good, nothing to do")

    _asyncio.run(_check())
