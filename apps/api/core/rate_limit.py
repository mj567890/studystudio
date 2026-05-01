"""
apps/api/core/rate_limit.py
共享速率限制模块（内存版，滑动窗口算法）

使用方式：
    from apps.api.core.rate_limit import (
        rate_limit_llm_heavy,      # 5/min — 课程生成等重量 LLM 调用
        rate_limit_llm_standard,   # 20/min — AI 出题/聊天等标准 LLM 调用
        rate_limit_celery,         # 10/min — Celery 任务触发
    )

    @router.post("/some-endpoint")
    async def handler(
        _rate: None = Depends(rate_limit_llm_heavy),
        ...
    ):

多 worker 部署建议升级为 Redis 版（当前内存实现在多进程中独立计数）。
"""
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status


class RateLimiter:
    """基于滑动窗口的速率限制器"""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._store: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self._store[key] = [t for t in self._store[key] if t > cutoff]
        if not self._store[key]:
            del self._store[key]

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        self._cleanup(key, now)
        if len(self._store.get(key, [])) >= self.max_requests:
            return False
        self._store[key].append(now)
        return True

    def reset_after(self, key: str) -> float:
        now = time.time()
        self._cleanup(key, now)
        if key not in self._store:
            return 0.0
        oldest = min(self._store[key])
        return max(0.0, oldest + self.window_seconds - now)


def _get_client_ip(request: Request) -> str:
    """获取客户端真实 IP（考虑反向代理）"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


# ════════════════════════════════════════════════════════════════
# 预设限制器实例
# ════════════════════════════════════════════════════════════════

# 登录/注册（IP 维度 — 用户未认证）
_login_limiter = RateLimiter(max_requests=20, window_seconds=60)    # 20 login/min
_register_limiter = RateLimiter(max_requests=5, window_seconds=60)  # 5 register/min

# LLM 调用（IP 维度）
_llm_heavy_limiter = RateLimiter(max_requests=5, window_seconds=60)     # 5/min — 课程生成
_llm_standard_limiter = RateLimiter(max_requests=20, window_seconds=60) # 20/min — 出题/聊天/评分

# Celery 任务触发（IP 维度）
_celery_limiter = RateLimiter(max_requests=10, window_seconds=60)       # 10/min


def reset_all_limiters() -> None:
    """重置所有速率限制器内部状态（仅用于测试）。"""
    for limiter in [_login_limiter, _register_limiter,
                    _llm_heavy_limiter, _llm_standard_limiter,
                    _celery_limiter]:
        limiter._store.clear()


# ════════════════════════════════════════════════════════════════
# 登录/注册（IP 维度 — 保持向后兼容）
# ════════════════════════════════════════════════════════════════

async def rate_limit_login(request: Request) -> None:
    ip = _get_client_ip(request)
    if not _login_limiter.is_allowed(f"login:{ip}"):
        retry_after = int(_login_limiter.reset_after(f"login:{ip}")) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_001", "msg": f"登录请求过于频繁，请 {retry_after} 秒后重试"},
            headers={"Retry-After": str(retry_after)},
        )


async def rate_limit_register(request: Request) -> None:
    ip = _get_client_ip(request)
    if not _register_limiter.is_allowed(f"register:{ip}"):
        retry_after = int(_register_limiter.reset_after(f"register:{ip}")) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_002", "msg": f"注册请求过于频繁，请 {retry_after} 秒后重试"},
            headers={"Retry-After": str(retry_after)},
        )


# ════════════════════════════════════════════════════════════════
# LLM 端点速率限制（IP 维度 — 与 login/register 一致）
# ════════════════════════════════════════════════════════════════

async def rate_limit_llm_heavy(request: Request) -> None:
    """
    重量 LLM 调用速率限制：5 次/分钟/IP。
    适用于：课程生成（start-generation）、重新生成（regenerate）。
    """
    ip = _get_client_ip(request)
    if not _llm_heavy_limiter.is_allowed(f"llm_heavy:{ip}"):
        retry_after = int(_llm_heavy_limiter.reset_after(f"llm_heavy:{ip}")) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_003",
                "msg": f"课程生成请求过于频繁，请 {retry_after} 秒后重试",
            },
            headers={"Retry-After": str(retry_after)},
        )


async def rate_limit_llm_standard(request: Request) -> None:
    """
    标准 LLM 调用速率限制：20 次/分钟/IP。
    适用于：AI 出题、AI 聊天、AI 评分、章节测验。
    """
    ip = _get_client_ip(request)
    if not _llm_standard_limiter.is_allowed(f"llm_std:{ip}"):
        retry_after = int(_llm_standard_limiter.reset_after(f"llm_std:{ip}")) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_004",
                "msg": f"AI 请求过于频繁，请 {retry_after} 秒后重试",
            },
            headers={"Retry-After": str(retry_after)},
        )


# ════════════════════════════════════════════════════════════════
# Celery 任务端点速率限制（IP 维度 — 与 login/register 一致）
# ════════════════════════════════════════════════════════════════

async def rate_limit_celery(request: Request) -> None:
    """
    Celery 任务触发速率限制：10 次/分钟/IP。
    适用于：start-generation、embeddings backfill、auto-review trigger。
    """
    ip = _get_client_ip(request)
    if not _celery_limiter.is_allowed(f"celery:{ip}"):
        retry_after = int(_celery_limiter.reset_after(f"celery:{ip}")) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_005",
                "msg": f"任务请求过于频繁，请 {retry_after} 秒后重试",
            },
            headers={"Retry-After": str(retry_after)},
        )
