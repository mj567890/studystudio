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


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
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
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _auto_review_async(space_id: str) -> None:
    from apps.api.core.llm_gateway import get_llm_gateway
    from sqlalchemy import text

    llm = get_llm_gateway()
    SF  = _make_session()

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

    for i in range(0, len(entities), 20):
        batch = entities[i:i+20]
        decisions = await _call_llm(llm, ROUND1_PROMPT, batch)
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
        for i in range(0, len(uncertain_batch), 20):
            batch2 = uncertain_batch[i:i+20]
            decisions2 = await _call_llm(llm, ROUND2_PROMPT, batch2)
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

    # ── 还有更多 pending 则继续 ──────────────────────────────────
    if len(entities) >= 100:
        auto_review_entities.apply_async(
            args=[space_id], queue="knowledge", countdown=3
        )
    else:
        # 本 space 全部处理完，推进文档状态
        await _finalize_documents(space_id)


async def _finalize_documents(space_id: str) -> None:
    """将本 space 下所有 extracted 状态文档推进到 reviewed。"""
    from sqlalchemy import text
    SF = _make_session()
    async with SF() as session:
        async with session.begin():
            await session.execute(
                text("""
                    UPDATE documents
                    SET document_status = 'reviewed', updated_at = now()
                    WHERE space_id = CAST(:sid AS uuid)
                      AND document_status = 'extracted'
                """),
                {"sid": space_id}
            )
    logger.info("Documents finalized", space_id=space_id)


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
