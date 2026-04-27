"""
apps/api/tasks/fork_tasks.py
Fork 空间异步任务：复制知识点 + blueprint 到新 space
"""
from __future__ import annotations
import asyncio
import os
import uuid as _uuid

import structlog

from celery import shared_task

from apps.api.tasks.task_tracker import task_tracker

logger = structlog.get_logger()


@shared_task(bind=True, max_retries=3, default_retry_delay=30,
             queue="low_priority", name="apps.api.tasks.fork_tasks.fork_space_task",
             on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def fork_space_task(self, task_id: str, source_space_id: str,
                    target_space_id: str, requested_by: str):
    logger.info("fork_space_task start", task_id=task_id,
                source=source_space_id, target=target_space_id)
    try:
        asyncio.run(_fork_space_async(task_id, source_space_id,
                                      target_space_id, requested_by))
    except Exception as exc:
        logger.error("fork_space_task failed", task_id=task_id, error=str(exc))
        asyncio.run(_set_task_status(task_id, "failed", str(exc)))
        raise self.retry(exc=exc)


def _make_session():
    from sqlalchemy.ext.asyncio import (
        create_async_engine, AsyncSession, async_sessionmaker
    )
    from sqlalchemy.pool import NullPool
    engine = create_async_engine(
        os.environ["DATABASE_URL"], poolclass=NullPool, echo=False
    )
    return async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)


async def _grant_document_access(
    task_id: str,
    source_space_id: str,
    target_space_id: str,
) -> None:
    """为 fork 空间授权访问源空间的文档（共享文档池，不复制文件）。"""
    from sqlalchemy import text

    async with _get_session() as session:
        try:
            # 获取源空间所有活跃文档
            rows = await session.execute(
                text("""
                    SELECT document_id::text FROM documents
                    WHERE space_id = CAST(:sid AS uuid)
                      AND deleted_at IS NULL
                """),
                {"sid": source_space_id},
            )
            doc_ids = [row[0] for row in rows.fetchall()]

            if not doc_ids:
                return

            # 批量插入授权记录
            inserted = 0
            for doc_id in doc_ids:
                result = await session.execute(
                    text("""
                        INSERT INTO space_document_access
                            (space_id, document_id, source_space_id)
                        VALUES
                            (CAST(:tsid AS uuid),
                             CAST(:did AS uuid),
                             CAST(:ssid AS uuid))
                        ON CONFLICT (space_id, document_id) DO NOTHING
                        RETURNING id
                    """),
                    {
                        "tsid": target_space_id,
                        "did":  doc_id,
                        "ssid": source_space_id,
                    },
                )
                if result.fetchone():
                    inserted += 1

            await session.commit()
            logger.info("Document access granted for fork",
                        task_id=task_id,
                        source=source_space_id,
                        target=target_space_id,
                        doc_count=len(doc_ids),
                        inserted=inserted)
        except Exception:
            await session.rollback()
            logger.warning("Failed to grant document access for fork",
                           task_id=task_id, exc_info=True)


async def _set_task_status(task_id: str, status: str,
                            error_msg: str | None = None) -> None:
    from sqlalchemy import text
    SessionFactory = _make_session()
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(
                text("""
                    UPDATE fork_tasks
                    SET status=:s, error_msg=:e, updated_at=now()
                    WHERE task_id=CAST(:tid AS uuid)
                """),
                {"s": status, "e": error_msg, "tid": task_id},
            )


async def _fork_space_async(task_id: str, source_space_id: str,
                             target_space_id: str, requested_by: str) -> None:
    from sqlalchemy import text

    await _set_task_status(task_id, "running")

    SessionFactory = _make_session()

    # ── 第一段：读取源空间全部资产 ──────────────────────────────
    async with SessionFactory() as session:

        # 1. 知识实体
        ents_r = await session.execute(
            text("""
                SELECT entity_id::text, name, entity_type, canonical_name,
                       domain_tag, space_type, short_definition,
                       detailed_explanation, review_status, is_core,
                       aliases, version
                FROM knowledge_entities
                WHERE space_id = CAST(:sid AS uuid)
            """),
            {"sid": source_space_id},
        )
        entities = [dict(r._mapping) for r in ents_r.fetchall()]

        # 2. 知识关系（两端都在本空间）
        if entities:
            eids = [e["entity_id"] for e in entities]
            rels_r = await session.execute(
                text("""
                    SELECT relation_id::text,
                           source_entity_id::text, target_entity_id::text,
                           relation_type, weight, review_status
                    FROM knowledge_relations
                    WHERE source_entity_id = ANY(CAST(:ids AS uuid[]))
                      AND target_entity_id = ANY(CAST(:ids AS uuid[]))
                """),
                {"ids": eids},
            )
            relations = [dict(r._mapping) for r in rels_r.fetchall()]
        else:
            relations = []

        # 3. published blueprint（只取最新一版）
        bp_r = await session.execute(
            text("""
                SELECT blueprint_id::text, topic_key, title, skill_goal,
                       status, version
                FROM skill_blueprints
                WHERE space_id = CAST(:sid AS uuid)
                  AND status = 'published'
                ORDER BY version DESC
            """),
            {"sid": source_space_id},
        )
        blueprints = [dict(r._mapping) for r in bp_r.fetchall()]

        # 4. 每个 blueprint 的 stages / chapters / entity_links
        bp_details: list[dict] = []
        for bp in blueprints:
            bid = bp["blueprint_id"]

            stages_r = await session.execute(
                text("""
                    SELECT stage_id::text, title, description,
                           stage_type, stage_order
                    FROM skill_stages
                    WHERE blueprint_id = CAST(:bid AS uuid)
                    ORDER BY stage_order
                """),
                {"bid": bid},
            )
            stages = [dict(r._mapping) for r in stages_r.fetchall()]

            for stage in stages:
                chaps_r = await session.execute(
                    text("""
                        SELECT chapter_id::text, title, objective,
                               task_description, pass_criteria,
                               common_mistakes, content_text, chapter_order
                        FROM skill_chapters
                        WHERE stage_id = CAST(:sid AS uuid)
                        ORDER BY chapter_order
                    """),
                    {"sid": stage["stage_id"]},
                )
                chapters = [dict(r._mapping) for r in chaps_r.fetchall()]

                for ch in chapters:
                    links_r = await session.execute(
                        text("""
                            SELECT entity_id::text, link_type
                            FROM chapter_entity_links
                            WHERE chapter_id = CAST(:cid AS uuid)
                        """),
                        {"cid": ch["chapter_id"]},
                    )
                    ch["entity_links"] = [dict(r._mapping)
                                          for r in links_r.fetchall()]

                stage["chapters"] = chapters

            bp_details.append({**bp, "stages": stages})

    logger.info("fork read done",
                entities=len(entities), relations=len(relations),
                blueprints=len(bp_details))

    # ── 第二段：写入目标空间 ────────────────────────────────────
    async with SessionFactory() as session:
        async with session.begin():

            # old_entity_id -> new_entity_id
            id_map: dict[str, str] = {}

            # 2a. 复制知识实体
            for ent in entities:
                old_id = ent["entity_id"]
                new_id = str(_uuid.uuid4())
                id_map[old_id] = new_id

                # 检查目标空间是否已有同名实体（幂等）
                exists = await session.execute(
                    text("""
                        SELECT entity_id::text FROM knowledge_entities
                        WHERE space_id = CAST(:sid AS uuid)
                          AND canonical_name = :cname
                        LIMIT 1
                    """),
                    {"sid": target_space_id, "cname": ent["canonical_name"]},
                )
                row = exists.fetchone()
                if row:
                    id_map[old_id] = str(row.entity_id)
                    continue

                import json as _json
                await session.execute(
                    text("""
                        INSERT INTO knowledge_entities
                            (entity_id, name, entity_type, canonical_name,
                             domain_tag, space_type, space_id, owner_id,
                             short_definition, detailed_explanation,
                             review_status, is_core, aliases, version)
                        VALUES
                            (CAST(:eid AS uuid), :name, :etype, :cname,
                             :dtag, :stype, CAST(:sid AS uuid),
                             CAST(:oid AS uuid),
                             :sdef, :dexp,
                             :rstatus, :is_core,
                             CAST(:aliases AS jsonb), :ver)
                    """),
                    {
                        "eid":     new_id,
                        "name":    ent["name"],
                        "etype":   ent["entity_type"],
                        "cname":   ent["canonical_name"],
                        "dtag":    ent["domain_tag"],
                        "stype":   ent.get("space_type", "personal"),
                        "sid":     target_space_id,
                        "oid":     requested_by,
                        "sdef":    ent.get("short_definition") or "",
                        "dexp":    ent.get("detailed_explanation") or "",
                        "rstatus": ent.get("review_status", "pending"),
                        "is_core": ent.get("is_core", False),
                        "aliases": _json.dumps(
                            ent.get("aliases") or [], ensure_ascii=False
                        ),
                        "ver":     ent.get("version", 1),
                    },
                )

            # 2b. 复制知识关系
            for rel in relations:
                src = id_map.get(rel["source_entity_id"])
                tgt = id_map.get(rel["target_entity_id"])
                if not src or not tgt:
                    continue
                exists = await session.execute(
                    text("""
                        SELECT 1 FROM knowledge_relations
                        WHERE source_entity_id = CAST(:src AS uuid)
                          AND target_entity_id = CAST(:tgt AS uuid)
                          AND relation_type = :rtype
                        LIMIT 1
                    """),
                    {"src": src, "tgt": tgt,
                     "rtype": rel["relation_type"]},
                )
                if exists.fetchone():
                    continue
                await session.execute(
                    text("""
                        INSERT INTO knowledge_relations
                            (relation_id, source_entity_id, target_entity_id,
                             relation_type, weight, review_status)
                        VALUES
                            (CAST(:rid AS uuid),
                             CAST(:src AS uuid), CAST(:tgt AS uuid),
                             :rtype, :weight, :rstatus)
                    """),
                    {
                        "rid":    str(_uuid.uuid4()),
                        "src":    src,
                        "tgt":    tgt,
                        "rtype":  rel["relation_type"],
                        "weight": float(rel.get("weight", 1.0)),
                        "rstatus": rel.get("review_status", "pending"),
                    },
                )

            # 2c. 复制 blueprints
            for bp in bp_details:
                new_bid = str(_uuid.uuid4())

                # ON CONFLICT 幂等：同一 space+topic_key 已存在则更新
                result = await session.execute(
                    text("""
                        INSERT INTO skill_blueprints
                            (blueprint_id, topic_key, title, skill_goal,
                             space_id, status, version)
                        VALUES
                            (CAST(:bid AS uuid), :tk, :title, :goal,
                             CAST(:sid AS uuid), 'published', 1)
                        ON CONFLICT (space_id, topic_key) DO UPDATE
                        SET title=EXCLUDED.title,
                            skill_goal=EXCLUDED.skill_goal,
                            status='published',
                            version=skill_blueprints.version+1,
                            updated_at=now()
                        RETURNING blueprint_id::text
                    """),
                    {
                        "bid":   new_bid,
                        "tk":    bp["topic_key"],
                        "title": bp["title"],
                        "goal":  bp.get("skill_goal"),
                        "sid":   target_space_id,
                    },
                )
                actual_bid = result.fetchone()[0]

                # 清空旧 stages（幂等重跑时）
                await session.execute(
                    text("DELETE FROM skill_stages "
                         "WHERE blueprint_id = CAST(:bid AS uuid)"),
                    {"bid": actual_bid},
                )

                # 2d. 复制 stages / chapters / entity_links
                for stage in bp["stages"]:
                    new_sid = str(_uuid.uuid4())
                    await session.execute(
                        text("""
                            INSERT INTO skill_stages
                                (stage_id, blueprint_id, title, description,
                                 stage_order, stage_type)
                            VALUES
                                (CAST(:sid AS uuid), CAST(:bid AS uuid),
                                 :title, :desc, :order, :stype)
                        """),
                        {
                            "sid":   new_sid,
                            "bid":   actual_bid,
                            "title": stage["title"],
                            "desc":  stage.get("description"),
                            "order": stage["stage_order"],
                            "stype": stage["stage_type"],
                        },
                    )

                    for ch in stage["chapters"]:
                        new_cid = str(_uuid.uuid4())
                        await session.execute(
                            text("""
                                INSERT INTO skill_chapters
                                    (chapter_id, stage_id, blueprint_id,
                                     title, objective, task_description,
                                     pass_criteria, common_mistakes,
                                     content_text, chapter_order)
                                VALUES
                                    (CAST(:cid AS uuid), CAST(:sid AS uuid),
                                     CAST(:bid AS uuid),
                                     :title, :obj, :task,
                                     :pass_, :mistakes,
                                     :content, :order)
                            """),
                            {
                                "cid":     new_cid,
                                "sid":     new_sid,
                                "bid":     actual_bid,
                                "title":   ch["title"],
                                "obj":     ch.get("objective"),
                                "task":    ch.get("task_description"),
                                "pass_":   ch.get("pass_criteria"),
                                "mistakes": ch.get("common_mistakes"),
                                "content": ch.get("content_text"),
                                "order":   ch["chapter_order"],
                            },
                        )

                        # entity_links：用 id_map 映射到新实体
                        for link in ch.get("entity_links", []):
                            new_eid = id_map.get(link["entity_id"])
                            if not new_eid:
                                continue
                            await session.execute(
                                text("""
                                    INSERT INTO chapter_entity_links
                                        (chapter_id, entity_id, link_type)
                                    VALUES
                                        (CAST(:cid AS uuid),
                                         CAST(:eid AS uuid), :lt)
                                    ON CONFLICT (chapter_id, entity_id)
                                    DO NOTHING
                                """),
                                {
                                    "cid": new_cid,
                                    "eid": new_eid,
                                    "lt":  link["link_type"],
                                },
                            )

    # ── 授权文档访问（共享源空间文档给 fork 空间）───────────────
    await _grant_document_access(task_id, source_space_id, target_space_id)
    logger.info("fork_space_async: document access granted",
                task_id=task_id, source=source_space_id, target=target_space_id)

    # ── 标记任务完成 ────────────────────────────────────────────
    await _set_task_status(task_id, "done")
    logger.info("fork_space_async done",
                task_id=task_id, target=target_space_id,
                entities=len(entities), blueprints=len(bp_details))
