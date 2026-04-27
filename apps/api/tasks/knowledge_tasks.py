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
from apps.api.tasks.task_tracker import task_tracker

logger = structlog.get_logger(__name__)

# ── FIX-1 信号已在 tutorial_tasks 中注册，此处无需重复 ──────────


# ════════════════════════════════════════════════════════════════
# FIX-F：文档解析任务（消费 file_uploaded 事件）
# ════════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=180,   # 3分钟：文档解析超时警告（允许事务收尾）
    time_limit=240,        # 4分钟：硬杀，防止槽位永久占用
    name="apps.api.tasks.knowledge_tasks.run_ingest",
    on_failure=task_tracker.on_failure,
    on_success=task_tracker.on_success,
)
def run_ingest(
    self,
    file_id: str,
    minio_key: str,
    space_type: str,
    space_id: str | None,
    owner_id: str,
    file_name: str,
    document_id: str | None = None,
):
    """
    消费 file_uploaded 事件，执行文档解析。
    解析完成后 ingest_service 内部会自动发布 document_parsed 事件，
    从而触发下游的 run_extraction 知识抽取任务。
    """
    logger.info("run_ingest start", file_id=file_id, file_name=file_name)
    try:
        asyncio.run(_run_ingest_async(
            file_id, minio_key, space_type, space_id, owner_id, file_name, document_id
        ))
        logger.info("run_ingest done", file_id=file_id)
    except Exception as exc:
        logger.error("run_ingest failed", file_id=file_id, error=str(exc))
        raise self.retry(exc=exc)

def _check_already_ingested(file_id: str) -> bool:
    """同步检查 document 是否已存在且不是初始状态，避免重复处理。"""
    import asyncio as _asyncio
    async def _check():
        from apps.api.core.db import get_independent_db
        from sqlalchemy import text
        async with get_independent_db() as db:
            r = await db.execute(
                text("SELECT document_status FROM documents WHERE file_id=CAST(:fid AS uuid) LIMIT 1"),
                {"fid": file_id}
            )
            row = r.fetchone()
            return row is not None and row.document_status not in ("uploaded",)
    return _asyncio.run(_check())


async def _run_ingest_async(
    file_id: str,
    minio_key: str,
    space_type: str,
    space_id: str | None,
    owner_id: str,
    file_name: str,
    document_id: str | None = None,
) -> None:
    from apps.api.core.db import get_independent_db, engine
    from apps.api.core.events import get_event_bus
    from apps.api.modules.knowledge.ingest_service import DocumentIngestService

    # 丢弃 fork 继承的旧连接句柄，必须在任何 DB 操作前执行
    # 否则会造成 "got Future attached to a different loop" 错误
    engine.sync_engine.dispose(close=False)
    await engine.dispose()

    # 幂等检查：document 已存在且不是初始状态，跳过重复处理
    from sqlalchemy import text as _text
    async with get_independent_db() as _db:
        _r = await _db.execute(
            _text("SELECT document_status FROM documents WHERE file_id=CAST(:fid AS uuid) LIMIT 1"),
            {"fid": file_id}
        )
        _row = _r.fetchone()
        if _row is not None and _row.document_status not in ("uploaded",):
            logger.info("run_ingest skipped, already processed", file_id=file_id, status=_row.document_status)
            return

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
            document_id=document_id,
        )

    # document_parsed 事件已由 ingest_service.ingest() 内部发布（含 3 次重连重试），
    # 此处不再重复发布，避免下游 run_extraction 收到重复事件导致并行竞态。


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
    soft_time_limit=None,   # 大文档 LLM 抽取可能耗时 30+ 分钟，不设软超时
    time_limit=None,        # 不设硬超时
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

        # 原子锁：防止多个 worker 并行处理同一文档
        # 只有成功将状态更新为 'extracting' 的 worker 可以继续
        lock_result = await session.execute(
            text("""
                UPDATE documents
                SET document_status = 'extracting', updated_at = NOW()
                WHERE document_id = :doc_id
                  AND document_status NOT IN ('extracting', 'extracted', 'embedding', 'reviewed', 'published')
                RETURNING document_id::text
            """),
            {"doc_id": document_id}
        )
        if lock_result.rowcount == 0:
            logger.info("run_extraction skip: another worker is processing or document already done",
                        document_id=document_id)
            return
        await session.commit()  # 锁提交，其他 workers 看到 extracting 状态

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
        domain_tag = await _resolve_domain_tag(session, space_id)
        all_entities: list[dict] = []
        all_relations: list[dict] = []
        entity_names_seen: set[str] = set()

        # 从 system_configs 加载截断上限（带 CONFIG 回退）
        truncation_limits = await _load_truncation_limits(session)

        # 2. 逐块抽取（四步管线），收集错误信息用于诊断
        chunk_errors: list[dict] = []
        for chunk in chunks:
            chunk_text = chunk["content"]
            chunk_id   = chunk["chunk_id"]

            try:
                # 步骤 1：实体识别（返回 (entities, error_msg)）
                raw_entities, err1 = await _step_entity_recognition(llm, chunk_text, truncation_limits)
                if err1:
                    chunk_errors.append({"chunk_id": chunk_id, "index": chunk["index_no"],
                                         "step": "recognition", "error": err1})
                if not raw_entities:
                    continue

                # 步骤 2：实体分类
                classified, err2 = await _step_entity_classification(llm, chunk_text, raw_entities, truncation_limits)
                if err2:
                    chunk_errors.append({"chunk_id": chunk_id, "index": chunk["index_no"],
                                         "step": "classification", "error": err2})

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
                    relations, err3 = await _step_relation_extraction(
                        llm, chunk_text, [e["entity_name"] for e in new_entities], truncation_limits
                    )
                    if err3:
                        chunk_errors.append({"chunk_id": chunk_id, "index": chunk["index_no"],
                                             "step": "relation", "error": err3})
                    all_relations.extend(relations)

            except Exception as e:
                logger.warning(
                    "Chunk extraction failed",
                    document_id=document_id,
                    chunk_id=chunk_id,
                    error=str(e),
                )
                chunk_errors.append({"chunk_id": chunk_id, "index": chunk["index_no"],
                                     "step": "unknown", "error": str(e)[:300]})
                continue  # 单块失败不阻断整体

        logger.info(
            "Extraction complete",
            document_id=document_id,
            entities=len(all_entities),
            relations=len(all_relations),
            errors=len(chunk_errors),
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

            # 过滤空内容知识点
            definition = entity.get("short_definition", "").strip()
            if not definition or definition in ("-", "—", "–"):
                logger.debug("Entity skipped, empty definition", name=entity_name)
                continue

            # 去重：同领域已有同名知识点（无论通过还是驳回）则跳过，不重复插入
            existing = await session.execute(
                text("SELECT entity_id::text FROM knowledge_entities WHERE canonical_name=:n AND domain_tag=:d LIMIT 1"),
                {"n": entity_name, "d": domain_tag}
            )
            existing_row = existing.fetchone()
            if existing_row:
                entity_name_to_id[entity_name] = existing_row[0]
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
                            "domain_tag":     domain_tag,
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
        # 如果所有 chunk 都提取失败（0 实体 + 有错误），标记为 failed 而非 extracted
        error_json = json.dumps(chunk_errors[:50], ensure_ascii=False) if chunk_errors else None
        actual_success = len(all_entities) > 0
        if not actual_success and chunk_errors:
            logger.warning("All chunks failed extraction, marking document as failed",
                           document_id=document_id, total_chunks=len(chunks), errors=len(chunk_errors))
        await _mark_document_extracted(session, document_id, success=actual_success, error_message=error_json)

        # 触发 AI 自动审核（extraction 完成后，对本 space 的 pending 实体自动分类）
        if space_id:
            try:
                from apps.api.tasks.auto_review_tasks import auto_review_entities
                # fix_review_queue_v1: 审核任务发到 knowledge.review，由专属 worker 处理
                # 避免与 run_extraction 共抢 celery_worker_knowledge 的 concurrency 槽
                auto_review_entities.apply_async(args=[space_id], queue="knowledge.review",
                                                 countdown=5)
                logger.info("auto_review_entities triggered", space_id=space_id)
            except Exception as _e:
                logger.warning("Failed to trigger auto_review", error=str(_e))


# ════════════════════════════════════════════════════════════════
# 四步管线子函数
# ════════════════════════════════════════════════════════════════

async def _resolve_domain_tag(session, space_id: str | None) -> str:
    """根据 knowledge_spaces 反推领域标签，未命中时回退到 general。"""
    from sqlalchemy import text

    if not space_id:
        return "general"

    result = await session.execute(
        text(
            """
                SELECT name
                FROM knowledge_spaces
                WHERE space_id::text = :space_id
                LIMIT 1
            """
        ),
        {"space_id": space_id},
    )
    row = result.fetchone()
    if row and row.name:
        return row.name
    return "general"


def _normalize_entity_candidates(raw_entities: object) -> list[dict]:
    """兼容 LLM 返回字符串数组或字典数组两种格式。"""
    if not isinstance(raw_entities, list):
        return []

    normalized: list[dict] = []
    seen_names: set[str] = set()
    for item in raw_entities:
        if isinstance(item, str):
            entity_name = item.strip()
            payload: dict = {"entity_name": entity_name}
        elif isinstance(item, dict):
            entity_name = str(item.get("entity_name") or item.get("name") or "").strip()
            payload = {**item, "entity_name": entity_name}
        else:
            continue

        if not entity_name or entity_name in seen_names:
            continue
        seen_names.add(entity_name)
        normalized.append(payload)

    return normalized


def _fallback_classified_entities(raw_entities: list[dict]) -> list[dict]:
    return [
        {
            "entity_name": e["entity_name"],
            "entity_type": e.get("entity_type", "concept") or "concept",
            "short_definition": e.get("short_definition", "") or "",
        }
        for e in _normalize_entity_candidates(raw_entities)
        if e.get("entity_name")
    ]

async def _step_entity_recognition(llm, chunk_text: str, limits: dict[str, int]) -> tuple[list[dict], str | None]:
    """步骤1：实体识别。失败返回空列表和错误信息，不抛异常。"""
    try:
        limit = limits.get("entity", 2000)
        prompt = ENTITY_RECOGNITION_PROMPT.format(text=chunk_text[:limit])
        resp   = await llm.generate(prompt, model_route="knowledge_extraction")
        data   = _safe_parse_json(resp)
        return _normalize_entity_candidates(data.get("entities", [])), None
    except Exception as e:
        err_msg = str(e)[:300]
        logger.debug("Entity recognition failed", error=err_msg)
        return [], err_msg


async def _step_entity_classification(
    llm, chunk_text: str, raw_entities: list[dict], limits: dict[str, int]
) -> tuple[list[dict], str | None]:
    """步骤2：实体分类。失败时退回原始实体列表（entity_type 默认 concept）。"""
    normalized_entities = _normalize_entity_candidates(raw_entities)
    if not normalized_entities:
        return [], None
    try:
        entity_names = json.dumps(
            [e["entity_name"] for e in normalized_entities if e.get("entity_name")],
            ensure_ascii=False
        )
        limit = limits.get("classify", 1500)
        prompt = ENTITY_CLASSIFICATION_PROMPT.format(
            entities=entity_names,
            text=chunk_text[:limit],
        )
        resp = await llm.generate(prompt, model_route="knowledge_extraction")
        data = _safe_parse_json(resp)
        classified = _normalize_entity_candidates(data.get("entities", []))
        if classified:
            return [
                {
                    "entity_name": e["entity_name"],
                    "entity_type": e.get("entity_type", "concept") or "concept",
                    "short_definition": e.get("short_definition", "") or "",
                }
                for e in classified
            ], None
        # LLM 返回空时，用原始实体列表兜底
        return _fallback_classified_entities(normalized_entities), None
    except Exception as e:
        err_msg = str(e)[:300]
        logger.debug("Entity classification failed", error=err_msg)
        return _fallback_classified_entities(normalized_entities), err_msg


async def _step_relation_extraction(
    llm, chunk_text: str, entity_names: list[str], limits: dict[str, int]
) -> tuple[list[dict], str | None]:
    """步骤3：关系识别。失败返回空列表和错误信息。"""
    try:
        limit = limits.get("relation", 1500)
        prompt = RELATION_EXTRACTION_PROMPT.format(
            entities=json.dumps(entity_names, ensure_ascii=False),
            text=chunk_text[:limit],
        )
        resp = await llm.generate(prompt, model_route="knowledge_extraction")
        data = _safe_parse_json(resp)
        return data.get("relations", []), None
    except Exception as e:
        err_msg = str(e)[:300]
        logger.debug("Relation extraction failed", error=err_msg)
        return [], err_msg


def _safe_parse_json(text: str) -> dict:
    """安全解析 LLM 输出的 JSON，容忍 markdown 代码块包裹和非法转义字符。"""
    import re
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    if not cleaned:
        return {}
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 修复 LLM 输出的非法反斜杠转义，如 \S \W 等
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', cleaned)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return {}


async def _load_truncation_limits(session) -> dict[str, int]:
    """从 system_configs 加载各步骤文本截断上限，缺失时回退到 CONFIG。

    配置键（与系统配置页面字段一一对应）：
      extraction.truncation.entity   — 实体识别
      extraction.truncation.classify — 实体分类
      extraction.truncation.relation — 关系提取
    """
    from apps.api.core.config import CONFIG
    from sqlalchemy import text as _text

    defaults = {
        "entity":   CONFIG.tutorial.extraction_truncation_entity,
        "classify": CONFIG.tutorial.extraction_truncation_classify,
        "relation": CONFIG.tutorial.extraction_truncation_relation,
    }
    try:
        result = await session.execute(
            _text("SELECT config_key, config_value FROM system_configs "
                  "WHERE config_key IN ("
                  "'extraction.truncation.entity',"
                  "'extraction.truncation.classify',"
                  "'extraction.truncation.relation')")
        )
        for row in result.fetchall():
            key = row.config_key.split(".")[-1]  # "extraction.truncation.entity" → "entity"
            try:
                defaults[key] = int(row.config_value)
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return defaults


async def _mark_document_extracted(session, document_id: str, success: bool, error_message: str | None = None) -> None:
    from sqlalchemy import text
    status = "extracted" if success else "failed"
    await session.execute(
        text("UPDATE documents SET document_status = :status, updated_at = NOW(), last_error = :error "
             "WHERE document_id = :doc_id"),
        {"status": status, "doc_id": document_id, "error": error_message}
    )
    await session.commit()

    # 发送用户通知
    try:
        # 查询文档 owner
        row = await session.execute(
            text("SELECT owner_id::text, title FROM documents WHERE document_id = :doc_id"),
            {"doc_id": document_id}
        )
        doc = row.fetchone()
        if doc and doc.owner_id:
            from apps.api.modules.knowledge.notification_router import send_notification
            if success:
                await send_notification(
                    user_id=doc.owner_id,
                    notification_type="document_complete",
                    title=f"文档「{doc.title}」知识点提取完成",
                    message="知识点已进入 AI 审核阶段，通过后将自动生成向量和课程。",
                    target_type="document",
                    target_id=document_id,
                )
            else:
                err_summary = (error_message or "未知错误")[:200]
                await send_notification(
                    user_id=doc.owner_id,
                    notification_type="document_failed",
                    title=f"文档「{doc.title}」处理失败",
                    message=f"知识点提取阶段失败：{err_summary}。系统将在 LLM 恢复后自动重试，你也可以手动重试。",
                    target_type="document",
                    target_id=document_id,
                )
    except Exception:
        pass  # 通知发送失败不影响主流程
