"""
tests/conftest.py
共享 fixtures：app client、认证 mock、数据库 mock

策略：
1. 模块级设置环境变量（DATABASE_URL 使用 PostgreSQL URL 以支持 pool_size）
2. fixture 函数内先导入核心模块，再 patch startup 事件依赖，最后导入 app
"""
import os

# ════════════════════════════════════════════════════════════════
# 环境预置（模块级，pytest 收集时即生效）
# PostgreSQL URL 支持 pool_size/max_overflow，且 create_async_engine 不立即连接
# ════════════════════════════════════════════════════════════════
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
os.environ.setdefault("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672/")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ════════════════════════════════════════════════════════════════
# 标准 mock user
# ════════════════════════════════════════════════════════════════
def _make_user(user_id: str = "00000000-0000-0000-0000-000000000001",
               roles: list | None = None) -> dict:
    return {
        "user_id": user_id,
        "email": "test@example.com",
        "nickname": "TestUser",
        "avatar_url": None,
        "status": "active",
        "roles": roles or ["learner"],
        "created_at": "2026-01-01T00:00:00",
    }


@pytest.fixture
def mock_user() -> dict:
    return _make_user()


@pytest.fixture
def mock_admin() -> dict:
    return _make_user(roles=["admin", "learner"])


# ════════════════════════════════════════════════════════════════
# 速率限制器状态重置（防止测试间状态累积）
# ════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """每个测试前重置速率限制器内部状态。"""
    from apps.api.core.rate_limit import reset_all_limiters
    reset_all_limiters()


# ════════════════════════════════════════════════════════════════
# 数据库 session mock
# ════════════════════════════════════════════════════════════════
@pytest.fixture
def mock_db():
    """返回一个支持 AsyncSession 基本操作的 mock"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.begin_nested = MagicMock()
    return db


# ════════════════════════════════════════════════════════════════
# 缓存的 app 实例（所有 client fixture 共享）
# ════════════════════════════════════════════════════════════════
_app_cache = None


def _get_or_create_app():
    """延迟导入 app，同时 mock 掉 startup 事件中的重依赖"""
    global _app_cache
    if _app_cache is not None:
        return _app_cache

    # Step 1: 先导入核心模块（此时 engine 已用 PostgreSQL URL 创建，不连接）
    import apps.api.core.db as db_module
    import apps.api.core.events as events_module
    import apps.api.core.storage as storage_module
    import apps.api.core.redis as redis_module

    # Step 2: mock 阻止 startup 事件连接外部服务
    # init_db → no-op
    db_module.init_db = AsyncMock()
    # event_bus → mock
    _mock_bus = MagicMock()
    _mock_bus.connect = AsyncMock()
    _mock_bus.disconnect = AsyncMock()
    _mock_bus.subscribe = AsyncMock()
    _mock_bus.publish = AsyncMock()
    events_module.get_event_bus = MagicMock(return_value=_mock_bus)
    # minio → mock
    storage_module.get_minio_client = MagicMock(return_value=MagicMock())
    # redis → mock
    redis_module.get_redis = AsyncMock(return_value=MagicMock())

    # Step 3: 导入 app（startup 事件处理程序注册，但依赖已 mock）
    from apps.api.main import app
    _app_cache = app
    return app


@pytest.fixture
def client(mock_user, mock_db):
    """创建已注入 mock 依赖的 TestClient"""
    from fastapi.testclient import TestClient
    app = _get_or_create_app()

    async def _override_get_db():
        yield mock_db

    async def _override_get_current_user():
        return mock_user

    original_overrides = app.dependency_overrides.copy()

    import apps.api.core.db as db_module
    from apps.api.modules.auth.router import get_current_user

    app.dependency_overrides[db_module.get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides = original_overrides


@pytest.fixture
def client_no_auth(mock_db):
    """未认证 client（get_current_user 抛出 401）"""
    from fastapi.testclient import TestClient
    from fastapi import HTTPException, status
    app = _get_or_create_app()

    async def _override_get_db():
        yield mock_db

    async def _override_get_current_user():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "msg": "Not authenticated"}
        )

    original_overrides = app.dependency_overrides.copy()

    import apps.api.core.db as db_module
    from apps.api.modules.auth.router import get_current_user

    app.dependency_overrides[db_module.get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides = original_overrides
