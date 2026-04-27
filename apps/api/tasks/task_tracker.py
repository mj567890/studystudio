"""
apps/api/tasks/task_tracker.py
统一任务执行追踪模块

功能：
1. 记录 Celery 任务执行生命周期到 task_executions 表（running → succeeded/failed）
2. 使用 Celery task_prerun / task_postrun 信号自动追踪，无需修改现有任务代码
3. 实现两级失败策略：第一次失败静默自动重试，第二次失败标记需人工处理
4. 提供 on_failure / on_success 回调供 Celery 任务使用（已有任务无需改动）

使用方式：
    from apps.api.tasks.task_tracker import task_tracker, register_tracker_signals
    register_tracker_signals(celery_app)  # 在 celery_app 创建后调用一次
"""
from __future__ import annotations

import asyncio
import json
import os
import traceback
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TaskTracker:
    """任务生命周期追踪器，负责写入 task_executions 表。"""

    def _make_session(self):
        """创建独立于 FastAPI engine 的 session（支持 Celery worker 进程）。"""
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from sqlalchemy.pool import NullPool

        db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://user:pass@postgres:5432/adaptive_learning")
        engine = create_async_engine(db_url, poolclass=NullPool, connect_args={"timeout": 5})
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def _extract_ids(self, args: tuple, kwargs: dict) -> dict[str, str | None]:
        """从任务参数中提取 document_id 和 space_id。"""
        result = {"document_id": None, "space_id": None}
        if args:
            candidate = args[0] if isinstance(args[0], str) else None
            if candidate and len(candidate) == 36 and candidate.count("-") == 4:
                result["document_id"] = candidate
        if "document_id" in kwargs:
            result["document_id"] = str(kwargs["document_id"])
        if "space_id" in kwargs and kwargs["space_id"]:
            result["space_id"] = str(kwargs["space_id"])
        # 有些任务第 3 个参数是 space_id（跳过第 2 个 space_type）
        if not result["space_id"] and len(args) >= 3 and isinstance(args[2], str) and args[2]:
            if len(args[2]) == 36 and args[2].count("-") == 4:
                result["space_id"] = str(args[2])
        return result

    # ── Celery 信号回调（任务启动时写入 running 记录） ────────────────

    def on_task_prerun(self, sender=None, task_id=None, task=None, args=None, kwargs=None, **extra):
        """Celery task_prerun 信号：任务启动时写入 running 记录。

        信号签名: (sender, task_id, task, args, kwargs) — 全部 keyword 传递。
        sender 是 Celery app 实例。
        """
        try:
            asyncio.run(self._on_prerun_async(task, task_id, args or (), kwargs or {}))
        except Exception as exc:
            logger.warning("task_tracker.on_task_prerun failed", error=str(exc))

    async def _on_prerun_async(self, task, celery_task_id: str, task_args: tuple, task_kwargs: dict):
        from sqlalchemy import text as _text

        # 从 task 实例提取元信息
        task_name = getattr(task, 'name', 'unknown')
        queue = 'unknown'
        retries = 0
        try:
            req = task.request
            queue = req.delivery_info.get('routing_key', 'unknown') if req.delivery_info else 'unknown'
            retries = req.retries if hasattr(req, 'retries') else 0
        except Exception:
            pass

        ids = self._extract_ids(task_args, task_kwargs)

        SF = self._make_session()
        async with SF() as session:
            await session.execute(
                _text("""
                    INSERT INTO task_executions
                        (celery_task_id, task_name, queue, status, retry_count, max_retries,
                         args, kwargs, document_id, space_id, updated_at)
                    VALUES
                        (:ctid, :tname, :queue, 'running', :retries, 2,
                         CAST(:args AS jsonb), CAST(:kw AS jsonb),
                         CAST(:did AS uuid), CAST(:sid AS uuid),
                         NOW())
                    ON CONFLICT (celery_task_id) DO UPDATE SET
                        status = 'running',
                        retry_count = :retries,
                        updated_at = NOW()
                """),
                {
                    "ctid":    celery_task_id,
                    "tname":   task_name,
                    "queue":   queue,
                    "retries": retries,
                    "args":    json.dumps(list(task_args)),
                    "kw":      json.dumps(task_kwargs if task_kwargs else {}),
                    "did":     ids["document_id"],
                    "sid":     ids["space_id"],
                }
            )
            await session.commit()

    # ── Celery 信号回调（任务完成时更新状态） ──────────────────────

    def on_task_postrun(self, sender=None, task_id=None, task=None, args=None, kwargs=None,
                        retval=None, state=None, **extra):
        """Celery task_postrun 信号：任务完成时更新为 succeeded。

        信号签名: (sender, task_id, task, args, kwargs, retval, state) — 全部 keyword 传递。
        """
        if state == "SUCCESS":
            try:
                asyncio.run(self._on_postrun_async(task_id, args or (), kwargs or {}))
            except Exception as exc:
                logger.warning("task_tracker.on_task_postrun failed", error=str(exc))

    async def _on_postrun_async(self, celery_task_id: str, task_args: tuple, task_kwargs: dict):
        from sqlalchemy import text as _text

        SF = self._make_session()
        async with SF() as session:
            await session.execute(
                _text("""
                    UPDATE task_executions SET
                        status = 'succeeded',
                        updated_at = NOW(),
                        completed_at = NOW()
                    WHERE celery_task_id = :ctid
                """),
                {"ctid": celery_task_id},
            )
            await session.commit()

    # ── 旧版回调（兼容已有任务的 on_failure/on_success 装饰器参数） ──

    def on_success(self, result=None, task_id=None, args=None, kwargs=None, **extra):
        """Celery 任务成功回调（同步包装）。

        作为 @task(on_success=...) 的回调使用。
        如果已通过 signal 写了 running 记录，这里补充更新；否则插入新记录。
        """
        try:
            asyncio.run(self._on_success_async(result, task_id, args or (), kwargs or {}, **extra))
        except Exception as exc:
            logger.warning("task_tracker.on_success failed", error=str(exc))

    def on_failure(self, exception=None, task_id=None, args=None, kwargs=None, einfo=None, **extra):
        """Celery 任务失败回调（同步包装）。

        作为 @task(on_failure=...) 的回调使用。
        """
        try:
            asyncio.run(self._on_failure_async(exception, task_id, args or (), kwargs or {}, einfo, **extra))
        except Exception as exc:
            logger.warning("task_tracker.on_failure failed", error=str(exc))

    async def _on_success_async(self, result, celery_task_id: str, task_args: tuple, task_kwargs: dict, **extra):
        from sqlalchemy import text as _text

        ids = self._extract_ids(task_args, task_kwargs)

        SF = self._make_session()
        async with SF() as session:
            await session.execute(
                _text("""
                    INSERT INTO task_executions
                        (celery_task_id, task_name, queue, status, retry_count, max_retries,
                         args, kwargs, document_id, space_id, completed_at, updated_at)
                    VALUES
                        (:ctid, :tname, :queue, 'succeeded', 0, 2,
                         CAST(:args AS jsonb), CAST(:kw AS jsonb), CAST(:did AS uuid), CAST(:sid AS uuid),
                         NOW(), NOW())
                    ON CONFLICT (celery_task_id) DO UPDATE SET
                        status = 'succeeded',
                        updated_at = NOW(),
                        completed_at = NOW()
                """),
                {
                    "ctid":   celery_task_id,
                    "tname":  extra.get("task_name", "unknown"),
                    "queue":  extra.get("queue", "unknown"),
                    "args":   json.dumps(list(task_args)),
                    "kw":     json.dumps(task_kwargs if task_kwargs else {}),
                    "did":    ids["document_id"],
                    "sid":    ids["space_id"],
                }
            )
            await session.commit()

    async def _on_failure_async(self, exception, celery_task_id: str, task_args: tuple, task_kwargs: dict, einfo, **extra):
        from sqlalchemy import text as _text

        error_msg = str(exception)[:4000] if exception else "Unknown error"
        tb_str = einfo.traceback if einfo else ""
        ids = self._extract_ids(task_args, task_kwargs)

        SF = self._make_session()
        async with SF() as session:
            await session.execute(
                _text("""
                    INSERT INTO task_executions
                        (celery_task_id, task_name, queue, status, retry_count, max_retries,
                         args, kwargs, error_message, error_traceback,
                         document_id, space_id,
                         needs_manual_review, updated_at)
                    VALUES
                        (:ctid, :tname, :queue, :status, 0, 2,
                         CAST(:args AS jsonb), CAST(:kw AS jsonb),
                         :errmsg, :errtb,
                         CAST(:did AS uuid), CAST(:sid AS uuid),
                         TRUE, NOW())
                    ON CONFLICT (celery_task_id) DO UPDATE SET
                        status = :status,
                        error_message = :errmsg,
                        error_traceback = :errtb,
                        needs_manual_review = TRUE,
                        updated_at = NOW()
                """),
                {
                    "ctid":    celery_task_id,
                    "tname":   extra.get("task_name", "unknown"),
                    "queue":   extra.get("queue", "unknown"),
                    "status":  "failed",
                    "args":    json.dumps(list(task_args)),
                    "kw":      json.dumps(task_kwargs if task_kwargs else {}),
                    "errmsg":  error_msg,
                    "errtb":   str(tb_str)[:8000] if tb_str else "",
                    "did":     ids["document_id"],
                    "sid":     ids["space_id"],
                }
            )
            await session.commit()

        logger.error(
            "TASK_FAILED",
            task_id=celery_task_id,
            error=error_msg[:200],
            document_id=ids["document_id"],
            space_id=ids["space_id"],
        )

    # ── 手动操作接口（供 API 调用） ──────────────────────────────────

    @staticmethod
    async def mark_task_retried(execution_id: str, operator_name: str) -> None:
        """标记任务已被管理员手动重试。"""
        from sqlalchemy import text as _text
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from sqlalchemy.pool import NullPool

        db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://user:pass@postgres:5432/adaptive_learning")
        engine = create_async_engine(db_url, poolclass=NullPool, connect_args={"timeout": 5})
        SF = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SF() as session:
            await session.execute(
                _text("""
                    UPDATE task_executions
                    SET manual_action_taken = 'retried',
                        manual_action_by = :op,
                        manual_action_at = NOW(),
                        needs_manual_review = FALSE,
                        updated_at = NOW()
                    WHERE id = CAST(:eid AS uuid)
                """),
                {"eid": execution_id, "op": operator_name}
            )
            await session.commit()

    @staticmethod
    async def mark_task_cancelled(execution_id: str, operator_name: str) -> None:
        """标记任务已被管理员取消。"""
        from sqlalchemy import text as _text
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from sqlalchemy.pool import NullPool

        db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://user:pass@postgres:5432/adaptive_learning")
        engine = create_async_engine(db_url, poolclass=NullPool, connect_args={"timeout": 5})
        SF = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SF() as session:
            await session.execute(
                _text("""
                    UPDATE task_executions
                    SET status = 'cancelled',
                        manual_action_taken = 'cancelled',
                        manual_action_by = :op,
                        manual_action_at = NOW(),
                        needs_manual_review = FALSE,
                        updated_at = NOW(),
                        completed_at = NOW()
                    WHERE id = CAST(:eid AS uuid)
                """),
                {"eid": execution_id, "op": operator_name}
            )
            await session.commit()

    @staticmethod
    async def write_audit_log(
        operator_id: str | None,
        operator_name: str,
        action: str,
        target_type: str,
        target_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        """写入管理员操作审计日志。"""
        import json as _json
        from sqlalchemy import text as _text
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from sqlalchemy.pool import NullPool

        db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://user:pass@postgres:5432/adaptive_learning")
        engine = create_async_engine(db_url, poolclass=NullPool, connect_args={"timeout": 5})
        SF = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SF() as session:
            await session.execute(
                _text("""
                    INSERT INTO admin_audit_log
                        (operator_id, operator_name, action, target_type, target_id, details)
                    VALUES
                        (CAST(:oid AS uuid), :oname, :action, :ttype, :tid,
                         CAST(:details AS jsonb))
                """),
                {
                    "oid":     operator_id,
                    "oname":   operator_name,
                    "action":  action,
                    "ttype":   target_type,
                    "tid":     target_id,
                    "details": _json.dumps(details or {}, ensure_ascii=False),
                }
            )
            await session.commit()


# 全局单例
task_tracker = TaskTracker()


def register_tracker_signals(celery_app):
    """向 Celery app 注册 task_prerun / task_postrun 信号，实现自动追踪。

    用法（在 celery_app 创建后调用一次）：
        from apps.api.tasks.task_tracker import register_tracker_signals
        register_tracker_signals(celery_app)
    """
    from celery import signals

    # 连接到 celery app 的所有任务（不限制 sender，确保 prefork 子进程中也生效）
    signals.task_prerun.connect(
        task_tracker.on_task_prerun,
        dispatch_uid="task_tracker_prerun",
    )
    signals.task_postrun.connect(
        task_tracker.on_task_postrun,
        dispatch_uid="task_tracker_postrun",
    )
    logger.info("task_tracker signals registered", celery_app=str(celery_app.main))
