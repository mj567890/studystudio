"""
apps/api/core/redis.py
Redis 异步客户端模块

提供全局单例 Redis 连接，用于 Celery 任务、MinIO 清理兜底等场景。
"""
from __future__ import annotations

import redis.asyncio as aioredis

from apps.api.core.config import CONFIG

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """获取 Redis 异步连接单例。"""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            CONFIG.redis.url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """关闭 Redis 连接（应用退出时调用）。"""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
