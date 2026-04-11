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
    echo=CONFIG.debug,
)


@event.listens_for(engine.sync_engine, "connect")
def on_connect(dbapi_conn, _connection_record) -> None:
    """
    asyncpg 连接建立时注册 pgvector 编解码器。
    asyncpg 的原始连接通过 _connection 属性获取，
    再调用 asyncio.get_event_loop().run_until_complete() 执行异步注册。
    """
    # asyncpg 通过 SQLAlchemy 适配层包装，原始连接在 _connection 属性中
    asyncpg_conn = dbapi_conn._connection

    import asyncio
    try:
        from pgvector.asyncpg import register_vector
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果事件循环正在运行（FastAPI 启动时），用 run_coroutine_threadsafe
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                register_vector(asyncpg_conn), loop
            )
            future.result(timeout=10)
        else:
            loop.run_until_complete(register_vector(asyncpg_conn))
    except Exception:
        # pgvector 注册失败不阻断启动，向量查询时再处理
        pass


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
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_independent_db() -> AsyncGenerator[AsyncSession, None]:
    """
    创建独立 session，不依赖任何请求生命周期。
    用于 BackgroundTasks、Celery 任务等场景。
    """
    async with async_session_factory() as session:
        async with session.begin():
            yield session


async def init_db() -> None:
    """应用启动时初始化数据库扩展。"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
