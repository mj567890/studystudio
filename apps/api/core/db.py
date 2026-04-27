"""
apps/api/core/db.py
数据库连接与会话管理
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from apps.api.core.config import CONFIG


# ── 引擎创建 ──────────────────────────────────────────────────────────────
engine = create_async_engine(
    CONFIG.database.url,
    pool_pre_ping=True,
    pool_size=CONFIG.database.pool_size,
    max_overflow=CONFIG.database.max_overflow,
    echo=False,  # SQL echo 噪音太大，需要时改回 CONFIG.debug
)


# on_connect 事件已移除：在同步事件里跑异步注册会污染连接状态
# pgvector 注册已移至 init_db() 中处理


# ── 会话工厂 ──────────────────────────────────────────────────────────────
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


# ── 依赖注入用的会话获取函数 ─────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends 使用，请求结束自动关闭 session。"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                await session.close()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_independent_db() -> AsyncGenerator[AsyncSession, None]:
    """
    创建独立 session，不依赖任何请求生命周期。
    用于 BackgroundTasks、Celery 任务等场景。

    无隐式事务：每条语句自动提交。需要原子性时调用方应使用
    async with session.begin(): 包裹多个操作。
    """
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """应用启动时初始化数据库扩展。"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
