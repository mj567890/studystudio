# 速率限制与空间权限 — 技术参考

**更新日期：** 2026-05-02
**范围：** Rate Limit 架构 + Space Access Control 覆盖

---

## 一、速率限制架构

### 模块位置

```
apps/api/core/rate_limit.py   — 共享速率限制模块（RateLimiter 类 + 预设限制器 + Depends 函数）
apps/api/modules/auth/router.py — 登录/注册 rate limit（从共享模块 re-export）
```

### RateLimiter 类

```python
class RateLimiter:
    """基于滑动窗口的速率限制器（内存版）"""
    def __init__(self, max_requests: int, window_seconds: int = 60)
    def is_allowed(self, key: str) -> bool   # 检查 + 记录
    def reset_after(self, key: str) -> float  # 下次可请求的秒数
```

**算法：** 滑动窗口，每秒清理过期记录。O(n) 清理，n = 窗口内请求数。

**限制：** 内存存储，多 worker 部署时独立计数。生产多副本建议升级 Redis 版（Lua 脚本实现 token bucket）。

### 预置限制器

| 限制器 | 阈值 | 维度 | 适用端点 |
|--------|------|------|----------|
| `_login_limiter` | 20/min | IP | `/auth/login` |
| `_register_limiter` | 5/min | IP | `/auth/register` |
| `_llm_heavy_limiter` | 5/min | IP | `start-generation`, `submit-calibration` |
| `_llm_standard_limiter` | 20/min | IP | `teaching/chat`, `placement-quiz`, `chapter-quiz` |
| `_celery_limiter` | 10/min | IP | `embeddings/backfill`, `auto-review/trigger` |

### Depends 函数

```python
from apps.api.core.rate_limit import (
    rate_limit_login,         # 登录
    rate_limit_register,      # 注册
    rate_limit_llm_heavy,     # 课程生成（5/min）
    rate_limit_llm_standard,  # AI 出题/聊天（20/min）
    rate_limit_celery,        # Celery 任务触发（10/min）
)

@router.post("/some-endpoint")
async def handler(
    _rate: None = Depends(rate_limit_llm_heavy),
    ...
):
```

超限时返回 `429 Too Many Requests` + `Retry-After` header + 结构化错误体：
```json
{"code": "RATE_003", "msg": "课程生成请求过于频繁，请 N 秒后重试"}
```

### 错误码

| 错误码 | 限制器 | 触发条件 |
|--------|--------|----------|
| RATE_001 | login | 登录 >20/min |
| RATE_002 | register | 注册 >5/min |
| RATE_003 | llm_heavy | 课程生成 >5/min |
| RATE_004 | llm_standard | AI 请求 >20/min |
| RATE_005 | celery | 任务触发 >10/min |

### 测试隔离

每个测试前通过 `conftest.py` autouse fixture 自动清空所有限制器状态：

```python
@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    from apps.api.core.rate_limit import reset_all_limiters
    reset_all_limiters()
```

---

## 二、空间权限检查覆盖

### 端点覆盖矩阵

| 端点 | `require_space_access` | 校验时机 |
|------|----------------------|----------|
| `GET /api/blueprints/{topic_key}` | ✅ | 获取 blueprint 后检查 `bp.space_id` |
| `GET /api/blueprints/{topic_key}/status` | ✅ | 同上 |
| `POST /api/blueprints/{topic_key}/publish` | ✅ | 获取 blueprint 后检查 `bp.space_id` |
| `POST /api/blueprints/{topic_key}/submit-calibration` | ✅ | 获取 blueprint 后检查 `bp.space_id` |
| **`POST /api/blueprints/{topic_key}/start-generation`** | **✅（2026-05-02 修复）** | **DB 查询前检查 `req.space_id`** |

### 实现模式

```python
# 模式 A：blueprint 已存在，用 bp.space_id 检查
bp = await repo.get_by_topic(topic_key)
if bp:
    await SpaceService(db).require_space_access(bp["space_id"], current_user["user_id"])

# 模式 B：新创建场景，用 req.space_id 检查（start-generation）
space_id = req.space_id
await SpaceService(db).require_space_access(space_id, current_user["user_id"])
```

### 权限被拒响应

```json
{"code": "SPACE_ACCESS_DENIED", "msg": "No access to this space"}
```
HTTP 403

---

## 三、安全测试覆盖

### 测试套件位置

```
tests/security/
├── test_auth_bypass.py          # 认证绕过（25 tests）
├── test_idor_permissions.py     # IDOR/越权（19 tests）
├── test_payload_injection.py    # Payload 注入（48 tests）
├── test_error_leakage.py        # 错误泄露（8 tests）
├── test_rate_limit_abuse.py     # Rate Limit 滥用（8 tests）
├── test_llm_prompt_abuse.py     # LLM Prompt 注入（19 tests）
└── test_celery_task_abuse.py    # Celery 滥用（9 tests）
```

### 运行

```bash
# 仅安全测试
pytest tests/security/ -v

# 全量回归
pytest tests/ -q
```

### Rate Limit 相关测试注意事项

测试中需要 mock `request: Request` 对象（TestClient 自动提供）。高频测试通过 `_reset_rate_limiters` fixture 隔离。如果新增测试涉及 rate limit 端点，确保 `conftest.py` 中的 fixture 正确清理状态。

---

## 四、升级路线

| 版本 | 计划 |
|------|------|
| 当前（内存版） | 单 worker 部署有效 |
| v2.3（Redis 版） | Lua 脚本 token bucket，多 worker 共享计数，按 user_id 维度 |
| v2.3（Token 预算） | 按 space_id 限制每日 LLM 调用次数 |
