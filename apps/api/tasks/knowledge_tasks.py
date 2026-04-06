"""
apps/api/tasks/knowledge_tasks.py
Block B：知识抽取 Celery 任务

修复记录：
  原始问题：此文件原本缺失，导致 document_parsed 事件无人处理，
            知识点永远不进入抽取→审核队列的流程。
  FIX-D:    新增 run_extraction 任务，订阅 document_parsed 事件后触发。
  FIX-F:    新增 run_ingest 任务，订阅 file_uploaded 事件后触发文档解析。
            这是管线的第一环——没有它，ingest_service 从未被调用，
            document_parsed 事件也不会产生。
"""
import asyncio
import json
import uuid

import structlog
from celery import signals as celery_signals

from apps.api.tasks.tutorial_tasks import celery_app  # 复用同一 Celery 实例

logger = structlog.get_logger(__name__)

# ── FIX-1 信号已在 tutorial_tasks 中注册，此处无需重复 ──────────


# ════════════════════════════════════════════════════════════════
# FIX-F：文档解析任务（消费 file_uploaded 事件）
# ════════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="apps.api.tasks.knowledge_tasks.run_ingest",
)
def run_ingest(
    self,
    file_id: str,
    minio_key: str,
    space_type: str,
    space_id: str | None,
    owner_id: str,
    file_name: str,
):
    """
    消费 file_uploaded 事件，执行文档解析。
    解析完成后 ingest_service 内部会自动发布 document_parsed 事件，
    从而触发下游的 run_extraction 知识抽取任务。
    """
    logger.info("run_ingest start", file_id=file_id, file_name=file_name)
    try:
        asyncio.run(_run_ingest_async(
            file_id, minio_key, space_type, space_id, owner_id, file_name
        ))
        logger.info("run_ingest done", file_id=file_id)
    except Exception as exc:
        logger.error("run_ingest failed", file_id=file_id, error=str(exc))
        raise self.retry(exc=exc)


async def _run_ingest_async(
    file_id: str,
    minio_key: str,
    space_type: str,
    space_id: str | None,
    owner_id: str,
    file_name: str,
) -> None:
    from apps.api.core.db import get_independent_db, engine
    from apps.api.core.events import get_event_bus
    from apps.api.modules.knowledge.ingest_service import DocumentIngestService

    # 丢弃 fork 继承的旧连接句柄（与 run_extraction 同理）
    engine.sync_engine.dispose(close=False)

    # FIX-I：Celery worker 进程中 EventBus 未连接，
    # 而 ingest_service.ingest() 最后需要 publish("document_parsed")。
    # 在此处确保连接，已连接时 connect() 是幂等的。
    event_bus = get_event_bus()
    if event_bus._connection is None or event_bus._connection.is_closed:
        await event_bus.connect()

    async with get_independent_db() as session:
        service = DocumentIngestService(session)
        await service.ingest_from_file_event(
            file_id=file_id,
            minio_key=minio_key,
            space_type=space_type,
            space_id=space_id,
            owner_id=owner_id,
            file_name=file_name,
        )


# ════════════════════════════════════════════════════════════════
# 知识抽取 Prompt 模板
# ════════════════════════════════════════════════════════════════

ENTITY_RECOGNITION_PROMPT = """请从以下文本中识别所有重要知识点（实体）。
只输出 JSON，格式：{{"entities": [{{"entity_name": "名称"}}]}}
不要输出其他任何内容。

文本：
{text}
"""

ENTITY_CLASSIFICATION_PROMPT = """请对以下知识点进行分类。
类型只能是：concept（概念）/ element（要素）/ flow（流程）/ case（案例）/ defense（防御措施）

输出 JSON，格式：{{"entities": [{{"entity_name": "名称", "entity_type": "类型", "short_definition": "一句话定义"}}]}}

知识点列表：
{entities}

参考文本：
{text}
"""

RELATION_EXTRACTION_PROMPT = """请识别以下知识点之间的关系。
关系类型：prerequisite_of（前置依赖）/ related_to（相关）/ part_of（组成部分）/ example_of（示例）

只输出 JSON，格式：{{"relations": [{{"source": "知识点A", "target": "知识点B", "relation_type": "类型"}}]}}
只输出能从文本中确认的关系，不要猜测。

知识点：{entities}
文本：{text}
"""


# ════════════════════════════════════════════════════════════════
# 知识抽取任务（消费 document_parsed 事件）
# ════════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="apps.api.tasks.knowledge_tasks.run_extraction",
)
def run_extraction(self, document_id: str, space_type: str, space_id: str | None):
    """
    C1：同步包装 + asyncio.run()，与 prefork 池兼容。
    从 document_chunks 读取分块，逐块运行四步抽取管线，
    结果写入 knowledge_entities（status='pending_review'）。
    """
    logger.info("run_extraction start", document_id=document_id)
    try:
        asyncio.run(_run_extraction_async(document_id, space_type, space_id))
        logger.info("run_extraction done", document_id=document_id)
    except Exception as exc:
        logger.error("run_extraction failed", document_id=document_id, error=str(exc))
        raise self.retry(exc=exc)


async def _run_extraction_async(
    document_id: str,
    space_type: str,
    space_id: str | None,
) -> None:
    from apps.api.core.db import get_independent_db, engine
    from apps.api.core.llm_gateway import get_llm_gateway

    # FIX-3：丢弃 fork 继承的旧连接句柄
    engine.sync_engine.dispose(close=False)

    async with get_independent_db() as session:
        from sqlalchemy import text

        # 1. 获取文档的所有分块
        chunks_result = await session.execute(
            text("""
                SELECT chunk_id::text, content, index_no
                FROM document_chunks
                WHERE document_id = :doc_id
                ORDER BY index_no
            """),
            {"doc_id": document_id}
        )
        chunks = [dict(r._mapping) for r in chunks_result.fetchall()]

        if not chunks:
            logger.warning("No chunks found", document_id=document_id)
            await _mark_document_extracted(session, document_id, success=False)
            return

        llm = get_llm_gateway()
        all_entities: list[dict] = []
        all_relations: list[dict] = []
        entity_names_seen: set[str] = set()

        # 2. 逐块抽取（四步管线）
        for chunk in chunks:
            chunk_text = chunk["content"]
            chunk_id   = chunk["chunk_id"]

            try:
                # 步骤 1：实体识别
                raw_entities = await _step_entity_recognition(llm, chunk_text)
                if not raw_entities:
                    continue

                # 步骤 2：实体分类
                classified = await _step_entity_classification(llm, chunk_text, raw_entities)

                # 去重（同名实体跨块只保留一次）
                new_entities = [
                    e for e in classified
                    if e.get("entity_name") and e["entity_name"] not in entity_names_seen
                ]
                for e in new_entities:
                    entity_names_seen.add(e["entity_name"])
                all_entities.extend(new_entities)

                # 步骤 3：关系识别（仅对有实体的块）
                if len(new_entities) >= 2:
                    relations = await _step_relation_extraction(
                        llm, chunk_text, [e["entity_name"] for e in new_entities]
                    )
                    all_relations.extend(relations)

            except Exception as e:
                logger.warning(
                    "Chunk extraction failed",
                    document_id=document_id,
                    chunk_id=chunk_id,
                    error=str(e),
                )
                continue  # 单块失败不阻断整体

        logger.info(
            "Extraction complete",
            document_id=document_id,
            entities=len(all_entities),
            relations=len(all_relations),
        )

        # 3. 写入 knowledge_entities（status=pending）
        # FIX-J：修正 INSERT 与表结构不匹配的问题：
        #   - 补充 name、domain_tag（NOT NULL 列）
        #   - 移除 source_document_id（表中不存在）
        #   - review_status 从 'pending_review' 改为 'pending'（CHECK 约束）
        #   - 移除无效的 ON CONFLICT（无对应唯一索引）
        entity_name_to_id: dict[str, str] = {}
        for entity in all_entities:
            entity_id = str(uuid.uuid4())
            entity_name = entity.get("entity_name", "").strip()
            if not entity_name:
                continue
            entity_name_to_id[entity_name] = entity_id
            try:
                async with session.begin_nested():
                    await session.execute(
                        text("""
                            INSERT INTO knowledge_entities
                              (entity_id, name, canonical_name, entity_type,
                               short_definition, domain_tag,
                               space_type, space_id, review_status)
                            VALUES
                              (:entity_id, :name, :canonical_name, :etype,
                               :definition, :domain_tag,
                               :space_type, :space_id, 'pending')
                        """),
                        {
                            "entity_id":      entity_id,
                            "name":           entity_name,
                            "canonical_name": entity_name,
                            "etype":          entity.get("entity_type", "concept"),
                            "definition":     entity.get("short_definition", ""),
                            "domain_tag":     "general",
                            "space_type":     space_type,
                            "space_id":       space_id,
                        }
                    )
            except Exception as e:
                logger.warning("Entity insert failed", name=entity_name, error=str(e))

        # 4. 写入 knowledge_relations
        # FIX-J：移除 source_document_id，修正 review_status 值
        for rel in all_relations:
            src_id = entity_name_to_id.get(rel.get("source", ""))
            tgt_id = entity_name_to_id.get(rel.get("target", ""))
            if not src_id or not tgt_id:
                continue
            try:
                async with session.begin_nested():
                    await session.execute(
                        text("""
                            INSERT INTO knowledge_relations
                              (relation_id, source_entity_id, target_entity_id,
                               relation_type, review_status)
                            VALUES
                              (:rid, :src, :tgt, :rtype, 'pending')
                        """),
                        {
                            "rid":    str(uuid.uuid4()),
                            "src":    src_id,
                            "tgt":    tgt_id,
                            "rtype":  rel.get("relation_type", "related_to"),
                        }
                    )
            except Exception as e:
                logger.warning("Relation insert failed", error=str(e))

        # 实体和关系写入完成，由 _mark_document_extracted 统一 commit
        await _mark_document_extracted(session, document_id, success=True)


# ════════════════════════════════════════════════════════════════
# 四步管线子函数
# ════════════════════════════════════════════════════════════════

async def _step_entity_recognition(llm, chunk_text: str) -> list[dict]:
    """步骤1：实体识别。失败返回空列表，不抛异常。"""
    try:
        prompt = ENTITY_RECOGNITION_PROMPT.format(text=chunk_text[:3000])
        resp   = await llm.generate(prompt, model_route="knowledge_extraction")
        data   = _safe_parse_json(resp)
        return data.get("entities", [])
    except Exception as e:
        logger.debug("Entity recognition failed", error=str(e))
        return []


async def _step_entity_classification(
    llm, chunk_text: str, raw_entities: list[dict]
) -> list[dict]:
    """步骤2：实体分类。失败时退回原始实体列表（entity_type 默认 concept）。"""
    if not raw_entities:
        return []
    try:
        entity_names = json.dumps(
            [e["entity_name"] for e in raw_entities if e.get("entity_name")],
            ensure_ascii=False
        )
        prompt = ENTITY_CLASSIFICATION_PROMPT.format(
            entities=entity_names,
            text=chunk_text[:2000],
        )
        resp = await llm.generate(prompt, model_route="knowledge_extraction")
        data = _safe_parse_json(resp)
        classified = data.get("entities", [])
        if classified:
            return classified
        # LLM 返回空时，用原始实体列表兜底
        return [{"entity_name": e["entity_name"], "entity_type": "concept", "short_definition": ""}
                for e in raw_entities if e.get("entity_name")]
    except Exception as e:
        logger.debug("Entity classification failed", error=str(e))
        return [{"entity_name": e["entity_name"], "entity_type": "concept", "short_definition": ""}
                for e in raw_entities if e.get("entity_name")]


async def _step_relation_extraction(
    llm, chunk_text: str, entity_names: list[str]
) -> list[dict]:
    """步骤3：关系识别。失败返回空列表。"""
    try:
        prompt = RELATION_EXTRACTION_PROMPT.format(
            entities=json.dumps(entity_names, ensure_ascii=False),
            text=chunk_text[:2000],
        )
        resp = await llm.generate(prompt, model_route="knowledge_extraction")
        data = _safe_parse_json(resp)
        return data.get("relations", [])
    except Exception as e:
        logger.debug("Relation extraction failed", error=str(e))
        return []


def _safe_parse_json(text: str) -> dict:
    """安全解析 LLM 输出的 JSON，容忍 markdown 代码块包裹。"""
    import re
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(cleaned)


async def _mark_document_extracted(session, document_id: str, success: bool) -> None:
    from sqlalchemy import text
    status = "extracted" if success else "extract_failed"
    await session.execute(
        text("UPDATE documents SET document_status = :status, updated_at = NOW() "
             "WHERE document_id = :doc_id"),
        {"status": status, "doc_id": document_id}
    )
    await session.commit()
