# API 端点测试套件（pytest + FastAPI TestClient）

**生成日期：** 2026-05-01
**测试总数：** 190（19 端点/权限 + 171 smoke）
**状态：** 全部通过，执行时间 3.41s

---

## 一、测试结构

```
tests/
├── conftest.py                 # 共享 fixtures（app client、认证 mock、数据库 mock）
├── pytest.ini                  # pytest 配置（asyncio auto、标记、路径）
├── api/
│   ├── __init__.py             # 包标记
│   ├── test_permissions.py     # 权限测试套件（7 tests）
│   └── test_endpoints.py       # 端点行为测试套件（12 tests）
└── test_smoke.py               # 安全与稳定性 smoke test（171 tests）
```

---

## 二、架构设计

### 2.1 Mock 注入策略（三层）

```
                    ┌─────────────────────────────┐
                    │  TestClient (FastAPI)        │
                    │  app.dependency_overrides    │
                    │                              │
                    │  get_db         → mock_db    │
                    │  get_current_user → mock_user│
                    └──────────┬──────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
    ┌───────▼───────┐  ┌──────▼──────┐  ┌───────▼──────────┐
    │ 源模块 patch   │  │ 源模块 patch│  │ 源模块 patch      │
    │ BlueprintRepo │  │ BlueprintSvc│  │ SpaceService      │
    │ .get_by_topic │  │ .get_blueprt│  │ .require_space_acc│
    └───────────────┘  └─────────────┘  └──────────────────┘
```

**核心原则：patch 源模块，非 router 模块。** router 内使用 local import（函数体内 `from apps.api.modules.space.service import SpaceService`），因此 patch 必须作用于源模块定义处。

### 2.2 环境变量预置（conftest.py 模块级）

```python
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")
# ... 等 8 个环境变量
```

**关键原因：** `apps/api/core/db.py` 在模块级调用 `create_async_engine(CONFIG.database.url, pool_size=..., max_overflow=...)`。SQLite 不支持 `pool_size`/`max_overflow` 参数，必须使用 PostgreSQL URL。`asyncpg` 引擎在 `create_async_engine` 时不立即连接，所以即使没有真实 PostgreSQL 也能成功创建引擎对象。

### 2.3 Startup 事件阻止

```python
def _get_or_create_app():
    # Step 1: 先导入核心模块
    import apps.api.core.db as db_module
    import apps.api.core.events as events_module
    import apps.api.core.storage as storage_module
    import apps.api.core.redis as redis_module

    # Step 2: mock startup 事件依赖
    db_module.init_db = AsyncMock()
    events_module.get_event_bus = MagicMock(return_value=_mock_bus)
    storage_module.get_minio_client = MagicMock(return_value=MagicMock())
    redis_module.get_redis = AsyncMock(return_value=MagicMock())

    # Step 3: 导入 app（startup 事件注册，但依赖已 mock）
    from apps.api.main import app
```

**关键原因：** `TestClient` 上下文管理器会触发 `on_event("startup")`，而 `init_db`/RabbitMQ/MinIO/Redis 连接会阻塞测试。预先 monkey-patch 后再导入 app，startup 事件执行的是 no-op mock。

---

## 三、各测试套件详情

### 3.1 权限测试（7 tests）

**文件：** `tests/api/test_permissions.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestUnauthenticatedAccess` | 4 | 未认证用户访问 get_blueprint/get_status/submit_calibration/start_generation 返回 401 |
| `TestSpaceAccessControl` | 2 | 正常访问 200 + 不存在的 blueprint 404 |
| `TestPublishPermissions` | 1 | learner 角色 publish 返回 403 |

**Mock 策略：** `patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint")` + `patch("apps.api.modules.space.service.SpaceService.require_space_access")`

### 3.2 端点行为测试（12 tests）

**文件：** `tests/api/test_endpoints.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestSubmitCalibration` | 5 | 正常提交(200 + confidence_score≥0.8)、blueprint不存在(404)、全空答案(confidence=0)、regenerate触发Celery任务、缺space_id(422) |
| `TestStartGeneration` | 4 | 无proposals(400)、无效proposal_id(400)、正常启动(200 + task_id)、缺space_id(422) |
| `TestGetBlueprint` | 3 | blueprint不存在(404)、正常获取(200)、space_id参数正确转发 |

**Mock 策略：**
- `patch("apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic")`
- `patch("apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint")`
- `patch("apps.api.modules.space.service.SpaceService.require_space_access")`
- `patch("apps.api.tasks.blueprint_tasks.synthesize_blueprint")`

**DB 执行 mock 模式：**
```python
def _exec_side(query, params):
    m = MagicMock()
    if "course_proposals" in str(query):
        row = MagicMock()
        row.__getitem__ = MagicMock(return_value=json.dumps(proposals))
        m.fetchone.return_value = row
    else:
        m.fetchone.return_value = None
    return m
mock_db.execute = AsyncMock(side_effect=_exec_side)
```

### 3.3 Smoke 测试（171 tests）

**文件：** `tests/test_smoke.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestPythonSyntax` | 34 (参数化) | 全量 `apps/api/*.py` AST 语法检查 |
| `TestNoDangerousFunctions` | 31 (参数化) | 禁止 `eval/exec/os.system/subprocess/__import__`，含已审计误报排除 |
| `TestNoBareExcept` | 34 (参数化) | 禁止裸 `except:` 子句 |
| `TestJWTSecretValidation` | 2 | 生产环境拒绝弱密钥、开发环境允许任意密钥 |
| `TestDocsSecurity` | 1 | 非 debug 模式下 `docs_url=None` |
| `TestSQLParameterization` | 3 | router 禁止 f-string SQL、repository 使用 `text()` + `:param` 绑定、`set_clause` 从开发者控制的 keys 构建 |

**误报排除机制：**
```python
KNOWN_SAFE = {
    "routers.py": "__import__",               # 动态 import 路由模块
    "tutorial_tasks.py": "__import__",        # 动态 import 任务
    "normalization_service.py": "__import__", # 动态 import 向量工具
    "tutorial_service.py": "eval",            # 正则匹配/非代码执行
}
```

---

## 四、测试覆盖矩阵（新增）

```
功能域                    │ 权限测试 │ 端点测试 │ Smoke │ 合计
─────────────────────────────────────────────────────────
未认证拦截                │    4     │    -     │   -   │   4
空间权限控制              │    2     │    -     │   -   │   2
Publish 权限（RBAC）      │    1     │    -     │   -   │   1
Submit Calibration        │    -     │    5     │   -   │   5
Start Generation          │    -     │    4     │   -   │   4
Get Blueprint             │    -     │    3     │   -   │   3
─────────────────────────────────────────────────────────
AST 语法检查              │    -     │    -     │  34   │  34
危险函数检测              │    -     │    -     │  31   │  31
裸 except 检测            │    -     │    -     │  34   │  34
JWT 密钥安全              │    -     │    -     │   2   │   2
Docs 安全                 │    -     │    -     │   1   │   1
SQL 参数化检查            │    -     │    -     │   3   │   3
─────────────────────────────────────────────────────────
总计                      │    7     │   12     │ 171   │ 190
```

---

## 五、运行方式

```bash
# 全量运行（含 API 端点 + smoke）
python -m pytest tests/ -v

# 仅 API 端点测试
python -m pytest tests/api/ -v

# 仅权限测试
python -m pytest tests/api/test_permissions.py -v

# 仅端点行为测试
python -m pytest tests/api/test_endpoints.py -v

# 仅 smoke test
python -m pytest tests/test_smoke.py -v

# 按关键词筛选
python -m pytest tests/ -v -k "calibration or generation"

# 含覆盖率报告
python -m pytest tests/ -v --cov=apps/api --cov-report=term-missing
```

---

## 六、Mock 策略速查表

| 被 mock 对象 | patch 目标 | 方式 |
|-------------|-----------|------|
| `get_db` | `app.dependency_overrides[db_module.get_db]` | dependency override |
| `get_current_user` | `app.dependency_overrides[get_current_user]` | dependency override |
| `init_db` | `apps.api.core.db.init_db` | `AsyncMock()` |
| `get_event_bus` | `apps.api.core.events.get_event_bus` | `MagicMock()` |
| `get_minio_client` | `apps.api.core.storage.get_minio_client` | `MagicMock()` |
| `get_redis` | `apps.api.core.redis.get_redis` | `AsyncMock()` |
| `BlueprintRepository.get_by_topic` | `apps.api.modules.skill_blueprint.repository.BlueprintRepository.get_by_topic` | `patch()` |
| `BlueprintService.get_blueprint` | `apps.api.modules.skill_blueprint.service.BlueprintService.get_blueprint` | `patch()` |
| `SpaceService.require_space_access` | `apps.api.modules.space.service.SpaceService.require_space_access` | `patch()` |
| `synthesize_blueprint` | `apps.api.tasks.blueprint_tasks.synthesize_blueprint` | `patch()` |
| `db.execute` | `mock_db.execute` (fixture) | `AsyncMock(side_effect=...)` |

---

## 七、已知局限与注意事项

| 局限 | 原因 | 缓解 |
|------|------|------|
| 不连接真实 PostgreSQL | 使用 `postgresql+asyncpg` URL 仅创建引擎对象，不实际连接 | `pool_size`/`max_overflow` 兼容；真实 DB 交互通过 `mock_db` fixture 模拟 |
| 不启动 Celery workers | 需要 RabbitMQ/Redis | `patch("apps.api.tasks.blueprint_tasks.synthesize_blueprint")` 阻止真实任务入队 |
| 不验证 OpenAI LLM 调用 | 需要 API Key | 端点测试仅验证路由层逻辑（请求解析 → 服务调用 → 响应格式） |
| Smoke test 误报排除 | 动态 `__import__` 是合法模式 | `KNOWN_SAFE` 字典排除已审计文件 |
| REST API 端点覆盖不全 | 当前仅覆盖 blueprint 核心端点 | 其他模块（document/media/space）端点待后续补充 |

---

## 八、问题排查记录

本轮测试套件生成过程中解决的关键问题：

| # | 问题 | 根因 | 解决方案 |
|---|------|------|---------|
| 1 | `TypeError: pool_size/max_overflow invalid for SQLite` | 默认 `DATABASE_URL=sqlite+aiosqlite://` 不支持连接池参数 | 改为 `postgresql+asyncpg://` URL（不实际连接） |
| 2 | `ModuleNotFoundError: No module named 'redis'` | 测试环境缺少 redis 包 | `pip install redis` |
| 3 | `AttributeError: 'coroutine' object has no attribute '_mapping'` | `AsyncMock()` 链式调用返回 coroutine 而非 MagicMock | 使用 `AsyncMock(side_effect=_exec_side)` 返回带 `fetchone` 的 `MagicMock` |
| 4 | Startup 事件阻塞测试 | `TestClient` 触发 `on_event("startup")` 连接真实服务 | 在导入 `apps.api.main` 前 monkey-patch `init_db`/`get_event_bus`/`get_minio_client`/`get_redis` |
| 5 | `AttributeError: router does not have the attribute 'SpaceService'` | router 内使用 local import，不在模块级 | 改为 patch 源模块：`apps.api.modules.space.service.SpaceService` |
| 6 | `TypeError: the JSON object must be str, not MagicMock` | `row.__getitem__` 默认返回 MagicMock | `row.__getitem__ = MagicMock(return_value=json.dumps(proposals))` |
| 7 | Smoke test 误报 `eval`/`__import__` | 动态 import 模式被检测为危险调用 | 添加 `KNOWN_SAFE` 白名单排除 |

---

*文档版本：v1.0*
*生成时间：2026-05-01*
*关联代码：tests/conftest.py, tests/pytest.ini, tests/api/test_permissions.py, tests/api/test_endpoints.py, tests/test_smoke.py*
