"""
apps/api/tasks/auto_review_tasks.py
AI 自动审核知识点任务
- 明显噪声词（人名/账号/路径等）自动驳回
- 高置信领域术语（confidence >= 0.85）自动通过
- 灰区保留 pending，等人工处理
遵循三段式架构：读取 / LLM / 写入 完全分离
"""
from __future__ import annotations
import asyncio, json, re
import structlog
from apps.api.tasks.tutorial_tasks import celery_app

logger = structlog.get_logger()

AUTO_REVIEW_PROMPT = """你是知识点质量审核专家。请对以下知识点列表逐一判断是否有独立学习价值。

判断规则：
- reject（直接驳回）：人名、账号名、密码、手机号、邮箱、文件路径、随机字符串、只在文章中偶然出现且无法独立解释的词
- approve（自动通过）：领域内标准术语、明确的技术概念、可复用的流程名称、典型攻击/防护方式
- manual（人工审核）：模糊词、同名多义词、可能有价值但不确定的词

知识点列表（JSON）：
{entities_json}

请严格按 JSON 数组输出，不含其他内容：
[
  {{
    "entity_id": "...",
    "decision": "approve|reject|manual",
    "confidence": 0.95,
    "reason": "简短原因（10字以内）",
    "suggest_type": "concept|element|flow|case|defense",
    "suggest_glossary": true
  }}
]"""


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def auto_review_entities(self, space_id: str):
    """异步自动审核指定 space 下所有 pending 知识点。"""
    logger.info("auto_review_entities start", space_id=space_id)
    try:
        asyncio.run(_auto_review_async(space_id))
    except Exception as exc:
        logger.error("auto_review_entities failed", space_id=space_id, error=str(exc))
        raise self.retry(exc=exc)


def _make_session():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool
    import os
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _auto_review_async(space_id: str) -> None:
    from apps.api.core.llm_gateway import get_llm_gateway
    from sqlalchemy import text

    llm = get_llm_gateway()
    SF = _make_session()

    # ══════════════════
    # 第一段：读取 pending 实体
    # ══════════════════
    async with SF() as session:
        result = await session.execute(
            text("""
                SELECT entity_id::text, canonical_name, entity_type,
                       short_definition, domain_tag
                FROM knowledge_entities
                WHERE space_id = CAST(:sid AS uuid)
                  AND review_status = 'pending'
                ORDER BY created_at
                LIMIT 80
            """),
            {"sid": space_id}
        )
        entities = [dict(r._mapping) for r in result.fetchall()]

    if not entities:
        logger.info("No pending entities to review", space_id=space_id)
        return

    logger.info("Auto reviewing entities", count=len(entities), space_id=space_id)

    # ══════════════════
    # 第二段：分批调用 LLM（每批 20 个）
    # ══════════════════
    all_decisions: list[dict] = []
    batch_size = 20

    for i in range(0, len(entities), batch_size):
        batch = entities[i:i + batch_size]
        entities_json = json.dumps(
            [{"entity_id": e["entity_id"],
              "name": e["canonical_name"],
              "type": e["entity_type"],
              "definition": (e["short_definition"] or "")[:100]} for e in batch],
            ensure_ascii=False
        )
        try:
            raw = await asyncio.wait_for(
                llm.generate(
                    AUTO_REVIEW_PROMPT.format(entities_json=entities_json),
                    model_route="knowledge_extraction"
                ),
                timeout=120
            )
            decisions = _parse_json_array(raw)
            if decisions:
                all_decisions.extend(decisions)
                logger.info("Batch reviewed", batch_start=i, count=len(decisions))
            else:
                logger.warning("LLM returned unparseable result for batch", batch_start=i)
        except Exception as e:
            logger.warning("Batch review failed, will retry via re-trigger",
                           batch_start=i, error=str(e))
            # 超时时直接退出当前任务，下次触发会从 pending 里重新捞
            break

    if not all_decisions:
        logger.warning("No decisions produced", space_id=space_id)
        return

    # ══════════════════
    # 第三段：写入审核结果
    # ══════════════════
    auto_approved = 0
    auto_rejected = 0
    manual_count  = 0

    SF2 = _make_session()
    async with SF2() as session:
        async with session.begin():
            for d in all_decisions:
                eid        = d.get("entity_id")
                decision   = d.get("decision", "manual")
                confidence = float(d.get("confidence", 0))
                reason     = d.get("reason", "")

                if not eid:
                    continue

                if decision == "reject":
                    await session.execute(
                        text("UPDATE knowledge_entities "
                             "SET review_status='rejected', updated_at=now() "
                             "WHERE entity_id=CAST(:eid AS uuid) AND review_status='pending'"),
                        {"eid": eid}
                    )
                    auto_rejected += 1

                elif decision == "approve" and confidence >= 0.85:
                    await session.execute(
                        text("UPDATE knowledge_entities "
                             "SET review_status='approved', updated_at=now() "
                             "WHERE entity_id=CAST(:eid AS uuid) AND review_status='pending'"),
                        {"eid": eid}
                    )
                    auto_approved += 1

                else:
                    # 保留 pending，写入 AI 建议到 short_definition 注释区
                    # 用 JSON 前缀标记，前端可读取
                    await session.execute(
                        text("UPDATE knowledge_entities "
                             "SET ai_review_confidence=:conf, ai_review_reason=:reason, "
                             "updated_at=now() "
                             "WHERE entity_id=CAST(:eid AS uuid) AND review_status='pending'"),
                        {"eid": eid, "conf": confidence, "reason": reason}
                    )
                    manual_count += 1

    logger.info("Auto review complete",
                space_id=space_id,
                auto_approved=auto_approved,
                auto_rejected=auto_rejected,
                manual_pending=manual_count)

    # 只有当本批有实际决策（approved 或 rejected）时才续批
    # 纯 manual_pending 说明 AI 无法判断，不续批避免无限循环
    if auto_approved + auto_rejected > 0:
        logger.info("More pending entities may exist, scheduling next batch",
                    space_id=space_id)
        from apps.api.tasks.auto_review_tasks import auto_review_entities
        auto_review_entities.apply_async(
            args=[space_id], queue="knowledge", countdown=3
        )


def _parse_json_array(raw: str) -> list:
    clean = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return []
