"""
apps/api/modules/knowledge/notification_router.py
用户通知 API — 查询、标记已读、发送通知
"""
from __future__ import annotations

import os as _os

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])


async def send_notification(
    user_id: str,
    notification_type: str,
    title: str,
    message: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> None:
    """从 Celery task 或 API 路由中发送通知（独立 engine，兼容 prefork）。"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool

    db_url = _os.environ.get("DATABASE_URL", "postgresql+asyncpg://user:pass@postgres:5432/adaptive_learning")
    engine = create_async_engine(db_url, poolclass=NullPool, connect_args={"timeout": 5})
    SF = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with SF() as session:
            await session.execute(
                text("""
                    INSERT INTO user_notifications (user_id, type, title, message, target_type, target_id)
                    VALUES (CAST(:uid AS uuid), :type, :title, :msg, :tt, CAST(:tid AS uuid))
                """),
                {
                    "uid": user_id,
                    "type": notification_type,
                    "title": title,
                    "msg": message,
                    "tt": target_type,
                    "tid": target_id,
                }
            )
            await session.commit()
        logger.debug("notification sent", user_id=user_id, type=notification_type)
    except Exception as exc:
        logger.warning("send_notification_failed", error=str(exc), user_id=user_id)
    finally:
        await engine.dispose()


@router.get("")
async def get_my_notifications(
    unread_only: bool = True,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取当前用户的未读通知。"""
    user_id = current_user["user_id"]
    where = "WHERE user_id = CAST(:uid AS uuid)"
    if unread_only:
        where += " AND is_read = FALSE"
    try:
        result = await db.execute(
            text(f"""
                SELECT id::text, type, title, message,
                       target_type, target_id::text,
                       is_read, created_at
                FROM user_notifications
                {where}
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"uid": user_id, "lim": limit}
        )
        notifications = []
        for row in result.fetchall():
            notifications.append({
                "id": row.id,
                "type": row.type,
                "title": row.title,
                "message": row.message,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "is_read": row.is_read,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        # 统计未读数量
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM user_notifications WHERE user_id = CAST(:uid AS uuid) AND is_read = FALSE"),
            {"uid": user_id}
        )
        unread_count = count_result.scalar() or 0
        return {
            "code": 200,
            "data": {
                "notifications": notifications,
                "unread_count": unread_count,
            }
        }
    except Exception as exc:
        logger.warning("get_notifications_failed", error=str(exc))
        return {"code": 200, "data": {"notifications": [], "unread_count": 0}}


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """标记通知为已读。"""
    try:
        await db.execute(
            text("UPDATE user_notifications SET is_read = TRUE WHERE id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)"),
            {"nid": notification_id, "uid": current_user["user_id"]}
        )
        await db.commit()
    except Exception as exc:
        logger.warning("mark_read_failed", error=str(exc))
    return {"code": 200, "msg": "ok"}


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """标记所有通知为已读。"""
    try:
        await db.execute(
            text("UPDATE user_notifications SET is_read = TRUE WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": current_user["user_id"]}
        )
        await db.commit()
    except Exception as exc:
        logger.warning("mark_all_read_failed", error=str(exc))
    return {"code": 200, "msg": "ok"}


@router.post("/{notification_id}/dismiss")
async def dismiss_notification(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """忽略通知（标记已读，相当于关闭但不跳转）。Phase 9.4"""
    try:
        await db.execute(
            text("UPDATE user_notifications SET is_read = TRUE WHERE id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)"),
            {"nid": notification_id, "uid": current_user["user_id"]}
        )
        await db.commit()
    except Exception as exc:
        logger.warning("dismiss_notification_failed", error=str(exc))
    return {"code": 200, "msg": "ok"}
