"""
apps/api/modules/admin/task_router.py
管理员任务监控与管理 API

功能：
- 失败任务列表（含筛选、分页、搜索）
- 单任务详情查看
- 单任务手动重试
- 单任务取消/撤销
- 任务统计摘要
- 批量操作（批量重试、一键清理已完成）
"""
import asyncio
import uuid as _uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user, require_role

logger = structlog.get_logger(__name__)

task_router = APIRouter(prefix="/api/admin/tasks", tags=["admin-tasks"])


# ════════════════════════════════════════════════════════════════
# 辅助：写入审计日志
# ════════════════════════════════════════════════════════════════
async def _audit(db: AsyncSession, operator: dict, action: str, target_type: str,
                 target_id: str = "", details: dict | None = None):
    """写入管理员操作审计日志。"""
    import json as _json
    nick = operator.get("nickname") or operator.get("email") or operator.get("user_id", "unknown")
    await db.execute(
        text("""
            INSERT INTO admin_audit_log
                (operator_id, operator_name, action, target_type, target_id, details)
            VALUES
                (CAST(:oid AS uuid), :oname, :action, :ttype, :tid,
                 CAST(:details AS jsonb))
        """),
        {
            "oid":     operator.get("user_id"),
            "oname":   str(nick),
            "action":  action,
            "ttype":   target_type,
            "tid":     str(target_id) if target_id else "",
            "details": _json.dumps(details or {}, ensure_ascii=False),
        }
    )
    # 不单独 commit，由调用方 commit


# ════════════════════════════════════════════════════════════════
# 请求/响应模型
# ════════════════════════════════════════════════════════════════
class TaskRetryRequest(BaseModel):
    execution_id: str


class TaskCancelRequest(BaseModel):
    execution_id: str


class BatchOperationRequest(BaseModel):
    execution_ids: list[str]


TASK_NAME_LABELS: dict[str, str] = {
    "run_ingest":                   "文档解析",
    "run_extraction":               "知识提取",
    "auto_review_entities":         "AI 自动审核",
    "embed_single_entity":          "实体向量化",
    "embed_document_chunks":        "文档块向量化",
    "backfill_entity_embeddings":   "向量补填",
    "synthesize_blueprint":         "蓝图/课程生成",
    "pregen_chapter_quizzes":       "章节测验预生成",
    "regenerate_all_chapters":      "全量章节重生成",
    "generate_skeleton":            "骨架生成",
    "generate_content":             "教程内容生成",
    "generate_annotations":         "薄弱点标注",
    "prebuild_placement_bank":      "冷启动题库预生成",
    "check_dlq":                    "死信队列巡检",
    "resume_pending_review":        "定时恢复检查",
    "fork_space_task":              "空间复制",
}

QUEUE_LABELS: dict[str, str] = {
    "knowledge":                "知识处理",
    "knowledge.review":         "知识审核",
    "tutorial":                 "教程生成",
    "low_priority":             "低优先级",
    "blueprint.synthesis.queue": "蓝图合成",
}


def _serialize_task(row) -> dict:
    """将 task_executions 行转为 API 响应格式。"""
    label = TASK_NAME_LABELS.get(row.task_name, row.task_name)
    queue_label = QUEUE_LABELS.get(row.queue, row.queue or "未知")
    return {
        "id":                   str(row.id),
        "celery_task_id":       row.celery_task_id,
        "task_name":            row.task_name,
        "task_label":           label,
        "queue":                row.queue,
        "queue_label":          queue_label,
        "status":               row.status,
        "retry_count":          row.retry_count,
        "max_retries":          row.max_retries,
        "args":                 row.args,
        "kwargs":               row.kwargs,
        "error_message":        row.error_message,
        "document_id":          str(row.document_id) if row.document_id else None,
        "space_id":             str(row.space_id) if row.space_id else None,
        "needs_manual_review":  bool(row.needs_manual_review),
        "manual_action_taken":  row.manual_action_taken,
        "manual_action_by":     row.manual_action_by,
        "manual_action_at":     row.manual_action_at.isoformat() if row.manual_action_at else None,
        "created_at":           row.created_at.isoformat() if row.created_at else None,
        "updated_at":           row.updated_at.isoformat() if row.updated_at else None,
        "completed_at":         row.completed_at.isoformat() if row.completed_at else None,
    }


# ════════════════════════════════════════════════════════════════
# 1. 任务统计摘要
# ════════════════════════════════════════════════════════════════
@task_router.get("/stats")
async def get_task_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取任务执行统计摘要。"""
    from sqlalchemy.exc import ProgrammingError

    result = {"total": 0, "failed": 0, "needs_review": 0, "retrying": 0,
              "succeeded_24h": 0, "by_name": [], "by_queue": []}

    try:
        # 总数和各状态计数
        row = (await db.execute(text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COUNT(*) FILTER (WHERE needs_manual_review = TRUE) AS needs_review,
                COUNT(*) FILTER (WHERE status = 'retrying') AS retrying,
                COUNT(*) FILTER (WHERE status = 'succeeded'
                    AND created_at > NOW() - INTERVAL '24 hours') AS succeeded_24h
            FROM task_executions
        """))).fetchone()
        if row:
            result["total"] = int(row.total or 0)
            result["failed"] = int(row.failed or 0)
            result["needs_review"] = int(row.needs_review or 0)
            result["retrying"] = int(row.retrying or 0)
            result["succeeded_24h"] = int(row.succeeded_24h or 0)

        # 按任务类型分组
        rows = (await db.execute(text("""
            SELECT task_name, COUNT(*) AS cnt,
                   COUNT(*) FILTER (WHERE needs_manual_review = TRUE) AS failed_cnt
            FROM task_executions
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY task_name
            ORDER BY cnt DESC
        """))).fetchall()
        result["by_name"] = [
            {
                "task_name":  r.task_name,
                "task_label": TASK_NAME_LABELS.get(r.task_name, r.task_name),
                "count":      int(r.cnt or 0),
                "failed":     int(r.failed_cnt or 0),
            }
            for r in rows
        ]

        # 按队列分组
        rows = (await db.execute(text("""
            SELECT queue, COUNT(*) AS cnt,
                   COUNT(*) FILTER (WHERE status = 'failed') AS failed_cnt
            FROM task_executions
            WHERE created_at > NOW() - INTERVAL '7 days'
              AND queue IS NOT NULL
            GROUP BY queue
            ORDER BY cnt DESC
        """))).fetchall()
        result["by_queue"] = [
            {
                "queue":       r.queue,
                "queue_label": QUEUE_LABELS.get(r.queue, r.queue),
                "count":       int(r.cnt or 0),
                "failed":      int(r.failed_cnt or 0),
            }
            for r in rows
        ]
    except ProgrammingError:
        # 表可能还不存在
        pass

    return {"code": 200, "data": result}


# ════════════════════════════════════════════════════════════════
# 2. 失败任务列表（需人工处理）
# ════════════════════════════════════════════════════════════════
@task_router.get("/failed")
async def list_failed_tasks(
    task_name: str = Query(""),
    status: str = Query(""),           # failed / retrying / ""
    needs_review: bool | None = None,  # 筛选是否需人工处理
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取失败/需人工处理的任务列表，支持多条件筛选和分页。"""
    from sqlalchemy.exc import ProgrammingError

    try:
        where_parts = []
        params: dict = {}

        if task_name:
            where_parts.append("te.task_name = :tname")
            params["tname"] = task_name

        if needs_review is not None:
            where_parts.append("te.needs_manual_review = :nrev")
            params["nrev"] = needs_review

        if status:
            where_parts.append("te.status = :status")
            params["status"] = status
        else:
            # 默认只查失败和重试中的
            where_parts.append("te.status IN ('failed', 'retrying', 'cancelled')")

        where_clause = " AND ".join(where_parts)
        if where_clause:
            where_clause = "WHERE " + where_clause

        # 总数
        total = 0
        count_result = await db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM task_executions te {where_clause}"),
            params
        )
        row = count_result.fetchone()
        if row:
            total = int(getattr(row, "cnt", 0) or 0)

        # 分页数据
        offset = (page - 1) * page_size
        params["lim"] = page_size
        params["off"] = offset

        result = await db.execute(
            text(f"""
                SELECT te.*,
                       d.title AS doc_title,
                       ks.name AS space_name
                FROM task_executions te
                LEFT JOIN documents d ON d.document_id = te.document_id
                LEFT JOIN knowledge_spaces ks ON ks.space_id = te.space_id
                {where_clause}
                ORDER BY
                    CASE te.status
                        WHEN 'failed' THEN 1
                        WHEN 'retrying' THEN 2
                        WHEN 'cancelled' THEN 3
                        ELSE 4
                    END,
                    te.created_at DESC
                LIMIT :lim OFFSET :off
            """),
            params
        )

        tasks = []
        for row in result.fetchall():
            t = _serialize_task(row)
            t["doc_title"] = getattr(row, "doc_title", None)
            t["space_name"] = getattr(row, "space_name", None)
            tasks.append(t)

        return {
            "code": 200,
            "data": {
                "tasks": tasks,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            }
        }
    except ProgrammingError:
        return {"code": 200, "data": {"tasks": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}}


# ════════════════════════════════════════════════════════════════
# 3. 全部任务列表（含筛选）
# ════════════════════════════════════════════════════════════════
@task_router.get("")
async def list_all_tasks(
    task_name: str = Query(""),
    status: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取全部任务执行记录，支持筛选和分页。"""
    from sqlalchemy.exc import ProgrammingError

    try:
        where_parts = []
        params: dict = {}

        if task_name:
            where_parts.append("te.task_name = :tname")
            params["tname"] = task_name

        if status:
            where_parts.append("te.status = :status")
            params["status"] = status

        where_clause = " AND ".join(where_parts)
        if where_clause:
            where_clause = "WHERE " + where_clause

        total = 0
        count_result = await db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM task_executions te {where_clause}"),
            params
        )
        row = count_result.fetchone()
        if row:
            total = int(getattr(row, "cnt", 0) or 0)

        offset = (page - 1) * page_size
        params["lim"] = page_size
        params["off"] = offset

        result = await db.execute(
            text(f"""
                SELECT te.*, d.title AS doc_title, ks.name AS space_name
                FROM task_executions te
                LEFT JOIN documents d ON d.document_id = te.document_id
                LEFT JOIN knowledge_spaces ks ON ks.space_id = te.space_id
                {where_clause}
                ORDER BY te.created_at DESC
                LIMIT :lim OFFSET :off
            """),
            params
        )

        tasks = []
        for row in result.fetchall():
            t = _serialize_task(row)
            t["doc_title"] = getattr(row, "doc_title", None)
            t["space_name"] = getattr(row, "space_name", None)
            tasks.append(t)

        return {
            "code": 200,
            "data": {
                "tasks": tasks,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            }
        }
    except ProgrammingError:
        return {"code": 200, "data": {"tasks": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}}


# ════════════════════════════════════════════════════════════════
# 4. 单任务详情
# ════════════════════════════════════════════════════════════════
@task_router.get("/{execution_id}")
async def get_task_detail(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取单个任务执行的完整详情，含错误堆栈。"""
    result = await db.execute(
        text("""
            SELECT te.*, d.title AS doc_title, ks.name AS space_name
            FROM task_executions te
            LEFT JOIN documents d ON d.document_id = te.document_id
            LEFT JOIN knowledge_spaces ks ON ks.space_id = te.space_id
            WHERE te.id = CAST(:eid AS uuid)
        """),
        {"eid": execution_id}
    )
    row = result.fetchone()
    if not row:
        return {"code": 404, "msg": "任务记录不存在"}

    t = _serialize_task(row)
    t["doc_title"] = getattr(row, "doc_title", None)
    t["space_name"] = getattr(row, "space_name", None)
    return {"code": 200, "data": t}


# ════════════════════════════════════════════════════════════════
# 5. 手动重试失败任务
# ════════════════════════════════════════════════════════════════
RETRY_ACTION_MAP: dict[str, dict] = {
    "run_ingest": {
        "import": "from apps.api.tasks.knowledge_tasks import run_ingest",
        "task": None,  # lazy import
        "args_from_row": lambda row: [
            row.kwargs.get("file_id", ""),
            row.kwargs.get("minio_key", ""),
            row.kwargs.get("space_type", "global"),
            row.kwargs.get("space_id"),
            row.kwargs.get("owner_id", ""),
            row.kwargs.get("file_name", ""),
        ],
        "queue": "knowledge",
    },
    "run_extraction": {
        "task": None,
        "args_from_row": lambda row: [
            row.args[0] if row.args and len(row.args) > 0 else (row.kwargs.get("document_id", "")),
            row.args[2] if row.args and len(row.args) > 2 else (row.kwargs.get("space_type", "global")),
            row.args[3] if row.args and len(row.args) > 3 else (row.kwargs.get("space_id")),
        ],
        "queue": "knowledge",
    },
    "auto_review_entities": {
        "task": None,
        "args_from_row": lambda row: [str(row.space_id) if row.space_id else ""],
        "queue": "knowledge.review",
    },
    "synthesize_blueprint": {
        "task": None,
        "args_from_row": lambda row: [
            row.kwargs.get("topic_key", "default"),
            str(row.space_id) if row.space_id else "",
        ],
        "queue": "knowledge",
    },
    "embed_single_entity": {
        "task": None,
        "args_from_row": lambda row: [row.args[0] if row.args and len(row.args) > 0 else ""],
        "queue": "knowledge",
    },
    "embed_document_chunks": {
        "task": None,
        "args_from_row": lambda row: [row.args[0] if row.args and len(row.args) > 0 else ""],
        "queue": "knowledge",
    },
    "generate_skeleton": {
        "task": None,
        "args_from_row": lambda row: row.args[:4] if row.args and len(row.args) >= 4 else [],
        "queue": "tutorial",
    },
    "generate_content": {
        "task": None,
        "args_from_row": lambda row: [row.args[0] if row.args and len(row.args) > 0 else ""],
        "queue": "tutorial",
    },
    "pregen_chapter_quizzes": {
        "task": None,
        "args_from_row": lambda row: row.args[:1] if row.args else [],
        "queue": "knowledge",
    },
}


@task_router.post("/{execution_id}/retry")
async def retry_task(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """手动重试单个失败任务。"""
    # 1. 查询任务记录
    result = await db.execute(
        text("SELECT * FROM task_executions WHERE id = CAST(:eid AS uuid)"),
        {"eid": execution_id}
    )
    row = result.fetchone()
    if not row:
        return {"code": 404, "msg": "任务记录不存在"}

    task_name = row.task_name
    task_args = row.args or []
    task_kwargs = row.kwargs or {}

    # 2. 查找重试策略
    retry_info = RETRY_ACTION_MAP.get(task_name)
    if not retry_info:
        # 通用任务：尝试用文档重试 API
        if row.document_id:
            from apps.api.tasks.knowledge_tasks import run_extraction
            run_extraction.apply_async(
                args=[str(row.document_id), "global", str(row.space_id) if row.space_id else None],
                queue="knowledge"
            )
        else:
            return {"code": 400, "msg": f"不支持重试的任务类型: {task_name}，请向系统管理员反馈"}

    # 3. 派发 Celery 任务
    try:
        if task_name == "run_ingest":
            from apps.api.tasks.knowledge_tasks import run_ingest
            run_ingest.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "run_extraction":
            from apps.api.tasks.knowledge_tasks import run_extraction
            run_extraction.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "auto_review_entities":
            from apps.api.tasks.auto_review_tasks import auto_review_entities
            auto_review_entities.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "synthesize_blueprint":
            from apps.api.tasks.blueprint_tasks import synthesize_blueprint
            synthesize_blueprint.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "embed_single_entity":
            from apps.api.tasks.embedding_tasks import embed_single_entity
            embed_single_entity.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "embed_document_chunks":
            from apps.api.tasks.embedding_tasks import embed_document_chunks
            embed_document_chunks.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "generate_skeleton":
            from apps.api.tasks.tutorial_tasks import generate_skeleton
            generate_skeleton.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "generate_content":
            from apps.api.tasks.tutorial_tasks import generate_content
            generate_content.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "pregen_chapter_quizzes":
            from apps.api.tasks.blueprint_tasks import pregen_chapter_quizzes
            pregen_chapter_quizzes.apply_async(
                args=retry_info["args_from_row"](row),
                queue=retry_info["queue"]
            )
        elif task_name == "regenerate_all_chapters":
            from apps.api.tasks.blueprint_tasks import regenerate_all_chapters
            regenerate_all_chapters.apply_async(
                args=[row.args[0] if row.args and len(row.args) > 0 else ""],
                queue=retry_info["queue"]
            )
        else:
            return {"code": 400, "msg": f"暂不支持重试该任务类型: {task_name}"}
    except Exception as exc:
        logger.error("Retry task dispatch failed", task_name=task_name, error=str(exc))
        return {"code": 500, "msg": f"派发任务失败: {str(exc)[:200]}"}

    # 4. 更新任务记录 + 写审计日志
    await db.execute(
        text("""
            UPDATE task_executions
            SET manual_action_taken = 'retried',
                manual_action_by = :op,
                manual_action_at = NOW(),
                needs_manual_review = FALSE,
                status = 'retrying',
                updated_at = NOW()
            WHERE id = CAST(:eid AS uuid)
        """),
        {"eid": execution_id,
         "op":  str(current_user.get("nickname") or current_user.get("email") or current_user.get("user_id"))}
    )
    await _audit(db, current_user, "retry_task", "task", execution_id,
                 {"task_name": task_name})
    await db.commit()

    return {"code": 200, "data": {"success": True, "message": f"已重新派发 {task_name} 任务到 {retry_info['queue']} 队列"}}


# ════════════════════════════════════════════════════════════════
# 6. 取消/忽略任务
# ════════════════════════════════════════════════════════════════
@task_router.post("/{execution_id}/cancel")
async def cancel_task(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """取消/忽略失败任务（不派发重试，标记为 cancelled）。"""
    result = await db.execute(
        text("SELECT * FROM task_executions WHERE id = CAST(:eid AS uuid)"),
        {"eid": execution_id}
    )
    row = result.fetchone()
    if not row:
        return {"code": 404, "msg": "任务记录不存在"}

    celery_task_id = row.celery_task_id

    # 尝试撤销 Celery 中正在运行的任务
    revoke_msg = ""
    if celery_task_id:
        try:
            from apps.api.tasks.tutorial_tasks import celery_app
            celery_app.control.revoke(celery_task_id, terminate=True)
            revoke_msg = "，已尝试撤销对应 Celery 任务"
        except Exception as exc:
            logger.warning("Celery revoke failed", task_id=celery_task_id, error=str(exc))
            revoke_msg = "（Celery 撤销失败，但已标记为 cancelled）"

    op_name = str(current_user.get("nickname") or current_user.get("email") or current_user.get("user_id"))
    await db.execute(
        text("""
            UPDATE task_executions
            SET status = 'cancelled',
                manual_action_taken = 'cancelled',
                manual_action_by = :op,
                manual_action_at = NOW(),
                needs_manual_review = FALSE,
                completed_at = NOW(),
                updated_at = NOW()
            WHERE id = CAST(:eid AS uuid)
        """),
        {"eid": execution_id, "op": op_name}
    )
    await _audit(db, current_user, "cancel_task", "task", execution_id,
                 {"task_name": row.task_name, "celery_task_id": celery_task_id})
    await db.commit()

    return {"code": 200, "data": {"success": True, "message": f"任务已取消{revoke_msg}"}}


# ════════════════════════════════════════════════════════════════
# 7. 批量操作：批量重试
# ════════════════════════════════════════════════════════════════
@task_router.post("/batch-retry")
async def batch_retry_tasks(
    req: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """批量重试多个失败任务。"""
    retried = 0
    errors: list[str] = []

    for eid in req.execution_ids:
        try:
            # 查询任务
            result = await db.execute(
                text("SELECT * FROM task_executions WHERE id = CAST(:eid AS uuid)"),
                {"eid": eid}
            )
            row = result.fetchone()
            if not row:
                errors.append(f"任务 {eid[:8]} 不存在")
                continue

            # 调用已存在的重试逻辑
            if row.document_id and row.task_name == "run_extraction":
                from apps.api.tasks.knowledge_tasks import run_extraction
                run_extraction.apply_async(
                    args=[str(row.document_id), "global", str(row.space_id) if row.space_id else None],
                    queue="knowledge"
                )
                retried += 1
            elif row.task_name == "auto_review_entities" and row.space_id:
                from apps.api.tasks.auto_review_tasks import auto_review_entities
                auto_review_entities.apply_async(args=[str(row.space_id)], queue="knowledge.review")
                retried += 1
            elif row.task_name == "synthesize_blueprint" and row.space_id:
                from apps.api.tasks.blueprint_tasks import synthesize_blueprint
                topic_key = row.kwargs.get("topic_key", "default") if row.kwargs else "default"
                synthesize_blueprint.apply_async(args=[topic_key, str(row.space_id)], queue="knowledge")
                retried += 1
            else:
                errors.append(f"任务 {eid[:8]} ({row.task_name}) 不支持批量重试")
                continue

            # 更新记录
            await db.execute(
                text("""
                    UPDATE task_executions
                    SET manual_action_taken = 'retried',
                        manual_action_by = :op,
                        manual_action_at = NOW(),
                        needs_manual_review = FALSE,
                        updated_at = NOW()
                    WHERE id = CAST(:eid AS uuid)
                """),
                {"eid": eid, "op": str(current_user.get("nickname") or current_user.get("user_id"))}
            )
        except Exception as exc:
            errors.append(f"{eid[:8]}: {str(exc)[:80]}")

    await _audit(db, current_user, "batch_retry_tasks", "task", "",
                 {"count": len(req.execution_ids), "retried": retried, "errors": errors})
    await db.commit()

    msg = f"已重试 {retried} 个任务"
    if errors:
        msg += f"，{len(errors)} 个失败"
    return {"code": 200, "data": {"success": True, "message": msg, "retried": retried, "errors": errors}}


# ════════════════════════════════════════════════════════════════
# 8. 可用的任务类型和队列列表（供前端筛选下拉）
# ════════════════════════════════════════════════════════════════
@task_router.get("/meta/filters")
async def get_task_filters(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """获取任务筛选条件选项。"""
    from sqlalchemy.exc import ProgrammingError

    task_names = []
    queues = []
    statuses = ["failed", "retrying", "succeeded", "cancelled"]

    try:
        rows = (await db.execute(text("""
            SELECT DISTINCT task_name FROM task_executions
            WHERE task_name IS NOT NULL
            ORDER BY task_name
        """))).fetchall()
        task_names = [
            {"value": r.task_name, "label": TASK_NAME_LABELS.get(r.task_name, r.task_name)}
            for r in rows
        ]
    except ProgrammingError:
        pass

    try:
        rows = (await db.execute(text("""
            SELECT DISTINCT queue FROM task_executions
            WHERE queue IS NOT NULL
            ORDER BY queue
        """))).fetchall()
        queues = [
            {"value": r.queue, "label": QUEUE_LABELS.get(r.queue, r.queue)}
            for r in rows
        ]
    except ProgrammingError:
        pass

    return {"code": 200, "data": {
        "task_names": task_names,
        "queues": queues,
        "statuses": statuses,
    }}
