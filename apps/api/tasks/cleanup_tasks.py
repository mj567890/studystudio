"""
apps/api/tasks/cleanup_tasks.py
定时清理任务：回收站过期清理 + MinIO 文件兜底清理
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import uuid as _uuid

import structlog

from celery import shared_task

from apps.api.tasks.task_tracker import task_tracker

logger = structlog.get_logger(__name__)

# 系统用户 ID（定时任务操作归属）
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"


def _make_session():
    from sqlalchemy.ext.asyncio import (
        create_async_engine, AsyncSession, async_sessionmaker,
    )
    from sqlalchemy.pool import NullPool
    engine = create_async_engine(
        os.environ["DATABASE_URL"], poolclass=NullPool, echo=False,
    )
    return async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)


# ═══════════════════════════════════════════════════════════════════
# 回收站过期空间清理（每日凌晨）
# ═══════════════════════════════════════════════════════════════════

@shared_task(
    bind=True, max_retries=1, default_retry_delay=300,
    queue="low_priority",
    name="apps.api.tasks.cleanup_tasks.cleanup_expired_spaces",
    on_failure=task_tracker.on_failure,
    on_success=task_tracker.on_success,
)
def cleanup_expired_spaces(self):
    """每天运行，彻底删除回收站中超过 30 天的空间（无 fork 引用时）。"""
    logger.info("cleanup_expired_spaces start")
    try:
        asyncio.run(_cleanup_expired_spaces_async())
    except Exception as exc:
        logger.error("cleanup_expired_spaces failed", error=str(exc))
        raise self.retry(exc=exc)


async def _cleanup_expired_spaces_async():
    from sqlalchemy import text

    SF = _make_session()
    deleted_count = 0
    skipped_count = 0

    async with SF() as session:
        # 查找过期空间（deleted_at 超过 30 天）
        result = await session.execute(
            text("""
                SELECT space_id::text FROM knowledge_spaces
                WHERE deleted_at IS NOT NULL
                  AND deleted_at < now() - INTERVAL '30 days'
            """),
        )
        expired_ids = [r[0] for r in result.fetchall()]

        if not expired_ids:
            logger.info("cleanup_expired_spaces: no expired spaces found")
            return {"deleted": 0, "skipped": 0}

        logger.info("cleanup_expired_spaces: found expired spaces",
                    count=len(expired_ids))

        for sid in expired_ids:
            # 检查 fork 引用（有引用则保留）
            refs = await session.execute(
                text("""
                    SELECT COUNT(*) FROM knowledge_spaces
                    WHERE fork_from_space_id IS NOT NULL
                      AND fork_from_space_id = CAST(:sid AS uuid)
                      AND deleted_at IS NULL
                """),
                {"sid": sid},
            )
            fork_count = int(refs.fetchone()[0])

            if fork_count > 0:
                logger.info("cleanup_expired_spaces: skipping space with fork refs",
                            space_id=sid, fork_count=fork_count)
                skipped_count += 1
                continue

            # 收集文件 URL（用于课后 MinIO 清理）
            file_urls_result = await session.execute(
                text("""
                    SELECT f.file_url FROM documents d
                    JOIN files f ON f.file_id = d.file_id
                    WHERE d.space_id = CAST(:sid AS uuid)
                      AND d.deleted_at IS NULL
                """),
                {"sid": sid},
            )
            file_urls = [r[0] for r in file_urls_result.fetchall()]

            # 事务内级联删除
            await _cascade_delete_space(session, sid)

            # 事务外：写入 MinIO 清理列表到 Redis
            if file_urls:
                await _enqueue_minio_cleanup(sid, file_urls)

            deleted_count += 1
            logger.info("cleanup_expired_spaces: space deleted",
                        space_id=sid)

    logger.info("cleanup_expired_spaces done",
                deleted=deleted_count, skipped=skipped_count)
    return {"deleted": deleted_count, "skipped": skipped_count}


async def _cascade_delete_space(session, space_id: str) -> None:
    """按依赖顺序级联删除空间所有数据。"""
    from sqlalchemy import text as _t

    delete_queries = [
        _t("DELETE FROM user_notifications WHERE target_type='space' AND target_id=CAST(:sid AS text)"),
        _t("DELETE FROM course_post_replies WHERE post_id IN "
           "(SELECT post_id FROM course_posts WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM course_posts WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM wall_replies WHERE post_id IN "
           "(SELECT post_id FROM wall_posts WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM wall_posts WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM community_curations WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM conversations WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM note_entity_links WHERE entity_id IN "
           "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM personal_entity_references WHERE ref_entity_id IN "
           "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM learner_knowledge_states WHERE entity_id IN "
           "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM chapter_quiz_attempts WHERE chapter_id IN "
           "(SELECT chapter_id::text FROM skill_chapters sc "
           "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
           "WHERE sb.space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM chapter_quizzes WHERE chapter_id IN "
           "(SELECT chapter_id::text FROM skill_chapters sc "
           "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
           "WHERE sb.space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM chapter_progress WHERE chapter_id IN "
           "(SELECT chapter_id::text FROM skill_chapters sc "
           "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
           "WHERE sb.space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM chapter_reflections WHERE chapter_id IN "
           "(SELECT chapter_id::text FROM skill_chapters sc "
           "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
           "WHERE sb.space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM chapter_entity_links WHERE chapter_id IN "
           "(SELECT chapter_id FROM skill_chapters sc "
           "JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id "
           "WHERE sb.space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM skill_chapters WHERE blueprint_id IN "
           "(SELECT blueprint_id FROM skill_blueprints WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM skill_stages WHERE blueprint_id IN "
           "(SELECT blueprint_id FROM skill_blueprints WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM skill_blueprints WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM tutorial_skeletons WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM knowledge_relations WHERE source_entity_id IN "
           "(SELECT entity_id FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM document_chunks WHERE document_id IN "
           "(SELECT document_id FROM documents WHERE space_id = CAST(:sid AS uuid))"),
        _t("DELETE FROM documents WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM space_document_access WHERE source_space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM fork_tasks WHERE source_space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM space_subscriptions WHERE space_id = CAST(:sid AS uuid)"),
        _t("DELETE FROM space_members WHERE space_id = CAST(:sid AS uuid)"),
        _t("UPDATE task_executions SET status='cancelled' WHERE space_id = CAST(:sid AS uuid) "
           "AND status IN ('pending','running')"),
        _t("DELETE FROM knowledge_spaces WHERE space_id = CAST(:sid AS uuid)"),
    ]

    for q in delete_queries:
        try:
            await session.execute(q, {"sid": space_id})
        except Exception:
            pass  # 表可能不存在，跳过

    await session.commit()


async def _enqueue_minio_cleanup(space_id: str, file_urls: list[str]) -> None:
    """将待清理的 MinIO 文件列表写入 Redis，供兜底任务重试。"""
    try:
        from apps.api.core.redis import get_redis
        redis = await get_redis()
        await redis.setex(
            f"cleanup:minio:{space_id}",
            86400 * 3,  # 3 天 TTL
            _json.dumps(file_urls),
        )
    except Exception:
        logger.warning("Failed to write MinIO cleanup list to Redis",
                       space_id=space_id)


# ═══════════════════════════════════════════════════════════════════
# MinIO 文件兜底清理（每小时）
# ═══════════════════════════════════════════════════════════════════

@shared_task(
    bind=True, max_retries=1, default_retry_delay=120,
    queue="low_priority",
    name="apps.api.tasks.cleanup_tasks.cleanup_pending_minio_files",
    on_failure=task_tracker.on_failure,
    on_success=task_tracker.on_success,
)
def cleanup_pending_minio_files(self):
    """每小时运行，重试 Redis 中排队等待清理的 MinIO 文件。"""
    logger.info("cleanup_pending_minio_files start")
    try:
        asyncio.run(_cleanup_pending_minio_files_async())
    except Exception as exc:
        logger.error("cleanup_pending_minio_files failed", error=str(exc))
        raise self.retry(exc=exc)


async def _cleanup_pending_minio_files_async():
    from apps.api.core.redis import get_redis
    from apps.api.core.storage import get_minio_client

    redis = await get_redis()
    minio = get_minio_client()

    # 扫描所有 cleanup:minio:* 键
    cursor = 0
    cleaned_keys = 0
    failed_files = 0

    while True:
        cursor, keys = await redis.scan(
            cursor, match="cleanup:minio:*", count=20,
        )
        for key in keys:
            try:
                data = await redis.get(key)
                if not data:
                    await redis.delete(key)
                    continue

                file_urls = _json.loads(data)
                remaining = []

                for url in file_urls:
                    # 从 URL 提取 MinIO key（格式: endpoint/bucket/key）
                    try:
                        # URL 格式: http://minio:9000/studystudio/path/to/file
                        parts = url.split("/", 3)
                        if len(parts) >= 4:
                            object_key = parts[3]
                        else:
                            object_key = parts[-1]

                        await minio.delete(object_key)
                    except Exception as exc:
                        logger.warning("MinIO file cleanup failed",
                                       url=url, error=str(exc))
                        remaining.append(url)
                        failed_files += 1

                if remaining:
                    # 还有失败的，更新列表并续期
                    await redis.setex(key, 86400 * 3, _json.dumps(remaining))
                else:
                    # 全部清理完毕
                    await redis.delete(key)
                    cleaned_keys += 1

            except Exception as exc:
                logger.warning("Failed to process cleanup key",
                               key=key, error=str(exc))

        if cursor == 0:
            break

    logger.info("cleanup_pending_minio_files done",
                cleaned_keys=cleaned_keys, failed_files=failed_files)
    return {"cleaned_keys": cleaned_keys, "failed_files": failed_files}
