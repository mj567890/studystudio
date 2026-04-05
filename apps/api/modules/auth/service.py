"""
apps/api/modules/auth/service.py
Block A：身份认证与授权服务

功能：用户注册、登录、JWT 签发与校验、RBAC 权限检查
"""
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import CONFIG

logger = structlog.get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── 密码工具 ──────────────────────────────────────────────────────────────
def _truncate_password(plain: str) -> str:
    """
    bcrypt 最多处理 72 字节，超出部分被静默忽略。
    passlib 新版本会直接报错，这里提前截断避免异常。
    中文密码每个字符占 3 字节，约 24 个中文字符就会触发限制。
    """
    encoded = plain.encode("utf-8")
    if len(encoded) > 72:
        encoded = encoded[:72]
    return encoded.decode("utf-8", errors="ignore")


def hash_password(plain: str) -> str:
    return pwd_context.hash(_truncate_password(plain))


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(_truncate_password(plain), hashed)


# ── JWT 工具 ──────────────────────────────────────────────────────────────
def create_access_token(user_id: str, roles: list[str]) -> str:
    payload: dict[str, Any] = {
        "sub":   user_id,
        "roles": roles,
        "iat":   datetime.now(timezone.utc),
        "exp":   datetime.now(timezone.utc) + timedelta(
            minutes=CONFIG.jwt.access_token_expire_minutes
        ),
    }
    return jwt.encode(payload, CONFIG.jwt.secret_key, algorithm=CONFIG.jwt.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, CONFIG.jwt.secret_key, algorithms=[CONFIG.jwt.algorithm])
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e


# ── 用户服务 ──────────────────────────────────────────────────────────────
class AuthService:

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(self, email: str, password: str, nickname: str) -> dict:
        # 检查邮箱唯一性
        result = await self.db.execute(
            text("SELECT user_id FROM users WHERE email = :email"),
            {"email": email}
        )
        if result.fetchone():
            raise ValueError("Email already registered")

        user_id = str(__import__("uuid").uuid4())
        password_hash = hash_password(password)

        await self.db.execute(
            text("""
                INSERT INTO users (user_id, email, password_hash, nickname)
                VALUES (:user_id, :email, :password_hash, :nickname)
            """),
            {"user_id": user_id, "email": email,
             "password_hash": password_hash, "nickname": nickname}
        )

        # 默认分配 learner 角色
        await self.db.execute(
            text("""
                INSERT INTO user_roles (user_id, role_id)
                SELECT :user_id, role_id FROM roles WHERE role_name = 'learner'
            """),
            {"user_id": user_id}
        )

        # 初始化学习者画像
        await self.db.execute(
            text("INSERT INTO learner_profiles (user_id) VALUES (:user_id)"),
            {"user_id": user_id}
        )

        await self.db.commit()
        logger.info("User registered", user_id=user_id, email=email)
        return {"user_id": user_id, "email": email, "nickname": nickname}

    async def login(self, email: str, password: str) -> dict:
        result = await self.db.execute(
            text("SELECT user_id, password_hash, status FROM users WHERE email = :email"),
            {"email": email}
        )
        row = result.fetchone()
        if not row:
            raise ValueError("Invalid credentials")
        if row.status != "active":
            raise ValueError("Account disabled")
        if not verify_password(password, row.password_hash):
            raise ValueError("Invalid credentials")

        roles = await self._get_user_roles(row.user_id)
        token = create_access_token(str(row.user_id), roles)

        logger.info("User logged in", user_id=row.user_id)
        return {"access_token": token, "token_type": "bearer", "roles": roles}

    async def get_current_user(self, user_id: str) -> dict:
        result = await self.db.execute(
            text("SELECT user_id, email, nickname, avatar_url, status, created_at "
                 "FROM users WHERE user_id = :user_id"),
            {"user_id": user_id}
        )
        row = result.fetchone()
        if not row:
            raise ValueError("User not found")
        roles = await self._get_user_roles(user_id)
        return {
            "user_id":    str(row.user_id),
            "email":      row.email,
            "nickname":   row.nickname,
            "avatar_url": row.avatar_url,
            "status":     row.status,
            "roles":      roles,
            "created_at": row.created_at.isoformat(),
        }

    async def _get_user_roles(self, user_id: str) -> list[str]:
        result = await self.db.execute(
            text("""
                SELECT r.role_name FROM roles r
                JOIN user_roles ur ON r.role_id = ur.role_id
                WHERE ur.user_id = :user_id
            """),
            {"user_id": user_id}
        )
        return [row.role_name for row in result.fetchall()]

    async def check_permission(self, user_id: str, permission_code: str) -> bool:
        result = await self.db.execute(
            text("""
                SELECT 1 FROM permissions p
                JOIN role_permissions rp ON p.permission_id = rp.permission_id
                JOIN user_roles ur ON rp.role_id = ur.role_id
                WHERE ur.user_id = :user_id AND p.permission_code = :code
            """),
            {"user_id": user_id, "code": permission_code}
        )
        return result.fetchone() is not None
