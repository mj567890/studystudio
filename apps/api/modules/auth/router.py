"""
apps/api/modules/auth/router.py
Block A：认证路由与依赖注入

安全审计 2026-04-27：
  - 添加 IP 级别速率限制（登录 20次/分钟，注册 5次/分钟）
  - 所有端点使用参数化查询
"""
from uuid import UUID
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, Request, status, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field, field_validator
import re
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.core.storage import get_minio_client
from apps.api.modules.auth.service import AuthService, decode_token

# import_avatar_fixed
router = APIRouter(prefix="/api", tags=["auth"])
security = HTTPBearer()


# ── 速率限制器（内存版，单进程有效；多 worker 部署建议升级为 Redis 版） ──
class RateLimiter:
    """基于滑动窗口的 IP 速率限制"""

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


_login_limiter = RateLimiter(max_requests=20, window_seconds=60)    # 20 login/min
_register_limiter = RateLimiter(max_requests=5, window_seconds=60)  # 5 register/min


def _get_client_ip(request: Request) -> str:
    """获取客户端真实 IP（考虑反向代理）"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


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


def _check_password_strength(v: str) -> str:
    if len(v) < 8:
        raise ValueError('密码至少 8 位')
    checks = [
        bool(re.search(r'[A-Z]', v)),
        bool(re.search(r'[a-z]', v)),
        bool(re.search(r'\d', v)),
        bool(re.search(r'[^A-Za-z0-9]', v)),
    ]
    if sum(checks) < 3:
        raise ValueError('密码须包含大写字母、小写字母、数字、特殊字符中至少三种')
    WEAK = {'password', 'password123', 'Aa123456', 'Abc12345', 'Admin123', 'Qwerty123'}
    if v.lower() in {w.lower() for w in WEAK}:
        raise ValueError('密码过于常见，请使用更复杂的密码')
    return v


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nickname: str = Field(min_length=1, max_length=100)

    @field_validator('password')
    @classmethod
    def password_strength(cls, v): return _check_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    roles: list[str]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        payload = decode_token(credentials.credentials)
        raw_user_id = payload.get("sub")
        if not raw_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "AUTH_001", "msg": "Not authenticated"}
            )
        user_id = str(UUID(str(raw_user_id)))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "msg": str(e)}
        )

    service = AuthService(db)
    try:
        return await service.get_current_user(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "msg": "User not found"}
        )


def require_role(*roles: str):
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        user_roles = set(current_user.get("roles", []))
        if not user_roles.intersection(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "AUTH_002", "msg": "Insufficient permissions"}
            )
        return current_user
    return _check


@router.post("/auth/register", status_code=201)
async def register(
    req: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(rate_limit_register),
) -> dict:
    service = AuthService(db)
    try:
        user = await service.register(req.email, req.password, req.nickname)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "AUTH_003", "msg": str(e)})
    return {"code": 201, "msg": "success", "data": user}


@router.post("/auth/login", response_model=dict)
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(rate_limit_login),
) -> dict:
    service = AuthService(db)
    try:
        result = await service.login(req.email, req.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "msg": str(e)}
        )
    return {"code": 200, "msg": "success", "data": result}


@router.get("/users/me")
async def get_me(current_user: dict = Depends(get_current_user)) -> dict:
    return {"code": 200, "msg": "success", "data": current_user}


class UpdateProfileRequest(BaseModel):
    nickname: str | None = None
    avatar_url: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)

    @field_validator('new_password')
    @classmethod
    def password_strength(cls, v): return _check_password_strength(v)


@router.patch("/users/me")
async def update_profile(
    req: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """更新昵称和头像。"""
    from sqlalchemy import text
    updates = {}
    if req.nickname is not None:
        updates["nickname"] = req.nickname
    if req.avatar_url is not None:
        updates["avatar_url"] = req.avatar_url
    if not updates:
        return {"code": 200, "msg": "success", "data": current_user}

    set_clause = ", ".join(f"{k}=:{k}" for k in updates)
    updates["uid"] = current_user["user_id"]
    await db.execute(
        text(f"UPDATE users SET {set_clause}, updated_at=now() WHERE user_id=CAST(:uid AS uuid)"),
        updates
    )
    await db.commit()
    # 返回更新后的数据
    row = await db.execute(
        text("SELECT user_id::text, email, nickname, avatar_url FROM users WHERE user_id=CAST(:uid AS uuid)"),
        {"uid": current_user["user_id"]}
    )
    r = row.fetchone()
    return {"code": 200, "msg": "success", "data": dict(r._mapping)}



@router.delete("/users/me")
async def deactivate_account(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # DELETE /api/users/me  软删除：将 status 置为 deleted
    uid = current_user["user_id"]
    async with db.begin():
        result = await db.execute(
            text(
                "UPDATE users SET status = 'deleted', updated_at = now() "
                "WHERE user_id = CAST(:uid AS uuid) AND status = 'active' "
                "RETURNING user_id"
            ),
            {"uid": uid},
        )
        if result.fetchone() is None:
            raise HTTPException(status_code=400, detail="账号状态异常，无法注销")
    return {"code": 0, "msg": "账号已注销", "data": None}


@router.post("/users/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # POST /api/users/me/avatar
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPEG / PNG / GIF / WebP 格式")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 5 MB")

    ext = Path(file.filename or "avatar").suffix.lower()
    # 安全审计 2026-04-27：仅允许标准图片扩展名，防御文件名注入
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"
    uid = current_user["user_id"]
    minio_key = f"avatars/{uid}{ext}"

    storage = get_minio_client()
    avatar_url = await storage.upload_bytes(minio_key, data, file.content_type or "image/jpeg")

    async with db.begin():
        await db.execute(
            text(
                "UPDATE users SET avatar_url = :url, updated_at = now() "
                "WHERE user_id = CAST(:uid AS uuid)"
            ),
            {"url": avatar_url, "uid": uid},
        )

    return {"code": 0, "msg": "ok", "data": {"avatar_url": avatar_url}}


@router.post("/users/me/password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """修改密码。需验证旧密码。"""
    from sqlalchemy import text
    from apps.api.modules.auth.service import verify_password, hash_password
    row = await db.execute(
        text("SELECT password_hash FROM users WHERE user_id=CAST(:uid AS uuid)"),
        {"uid": current_user["user_id"]}
    )
    r = row.fetchone()
    if not r or not verify_password(req.old_password, r.password_hash):
        raise HTTPException(400, detail={"code": "AUTH_002", "msg": "旧密码不正确"})
    new_hash = hash_password(req.new_password)
    await db.execute(
        text("UPDATE users SET password_hash=:h, updated_at=now() WHERE user_id=CAST(:uid AS uuid)"),
        {"h": new_hash, "uid": current_user["user_id"]}
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"msg": "密码已更新"}}
