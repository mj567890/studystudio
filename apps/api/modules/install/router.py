"""
apps/api/modules/install/router.py
系统安装向导 —— 公开接口，创建首位管理员并初始化系统配置

用法：
  1. GET  /api/install/status   检测系统是否已初始化
  2. POST /api/install          执行安装（仅限未初始化状态）

安全：
  - POST /install 使用 SELECT ... FOR UPDATE 序列化并发请求
  - 安装完成后 POST /install 永久拒绝进一步请求
  - 所有接口无需认证（公开）
"""
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import text

from apps.api.core.db import async_session_factory, init_db
from apps.api.modules.auth.router import _check_password_strength
from apps.api.modules.auth.service import hash_password

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["install"])


class InstallRequest(BaseModel):
    admin_email:      EmailStr
    admin_password:   str = Field(min_length=8)
    admin_nickname:   str = Field(min_length=1, max_length=100)
    site_name:        str = Field(default="", max_length=255)
    copyright:        str = Field(default="", max_length=500)
    registration_agreement: str = Field(default="", max_length=5000)

    @field_validator("admin_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _check_password_strength(v)


@router.get("/install/status")
async def install_status() -> dict:
    """检测系统是否已完成安装。"""
    try:
        await init_db()
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT config_value FROM system_configs WHERE config_key = 'init_completed'")
            )
            row = result.fetchone()
            init_completed = bool(row and row.config_value == "true")
        return {"code": 200, "msg": "success", "data": {"init_completed": init_completed}}
    except Exception as e:
        logger.error("install_status_failed", error=str(e))
        # 连不上数据库时默认为未安装，避免阻塞首次访问
        return {"code": 200, "msg": "success", "data": {"init_completed": True}}


@router.post("/install", status_code=201)
async def do_install(req: InstallRequest) -> dict:
    """执行系统安装：创建管理员 + 写入系统配置。仅限未初始化状态下调用一次。"""
    await init_db()

    async with async_session_factory() as session:
        async with session.begin():
            # ── 1. 原子检查是否已安装（FOR UPDATE 串行化并发请求） ──
            result = await session.execute(
                text("SELECT config_value FROM system_configs WHERE config_key = 'init_completed' FOR UPDATE")
            )
            row = result.fetchone()
            if row and row.config_value == "true":
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INSTALL_001", "msg": "系统已初始化，禁止重复安装"}
                )

            # ── 2. 检查邮箱是否已注册 ──
            result = await session.execute(
                text("SELECT user_id FROM users WHERE email = :email"),
                {"email": req.admin_email}
            )
            if result.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INSTALL_002", "msg": "该邮箱已被注册"}
                )

            # ── 3. 创建管理员用户 ──
            user_id = str(uuid4())
            pw_hash = hash_password(req.admin_password)

            await session.execute(
                text("""
                    INSERT INTO users (user_id, email, password_hash, nickname)
                    VALUES (CAST(:uid AS uuid), :email, :pw_hash, :nickname)
                """),
                {"uid": user_id, "email": req.admin_email,
                 "pw_hash": pw_hash, "nickname": req.admin_nickname}
            )

            # 赋予 admin 角色
            result = await session.execute(
                text("SELECT role_id FROM roles WHERE role_name = 'admin'")
            )
            admin_role = result.fetchone()
            if admin_role:
                await session.execute(
                    text("INSERT INTO user_roles (user_id, role_id) VALUES (CAST(:uid AS uuid), :rid)"),
                    {"uid": user_id, "rid": admin_role.role_id}
                )

            # 创建学习者画像
            await session.execute(
                text("INSERT INTO learner_profiles (user_id) VALUES (CAST(:uid AS uuid))"),
                {"uid": user_id}
            )

            # ── 4. 写入系统配置 ──
            configs = [
                ("site_name",               req.site_name),
                ("site_copyright",          req.copyright),
                ("registration_agreement",  req.registration_agreement),
                ("init_completed",          "true"),
            ]
            for key, value in configs:
                await session.execute(
                    text("""
                        INSERT INTO system_configs (config_key, config_value, updated_at)
                        VALUES (:key, :value, NOW())
                        ON CONFLICT (config_key) DO UPDATE SET config_value = :value, updated_at = NOW()
                    """),
                    {"key": key, "value": value}
                )

        # 事务提交成功
        logger.info("install_completed",
                     admin_email=req.admin_email, user_id=user_id, site_name=req.site_name)

    return {
        "code": 201,
        "msg": "系统安装完成，请使用管理员账号登录",
        "data": {
            "admin_user_id":    user_id,
            "site_name":        req.site_name,
            "init_completed":   True,
        }
    }
