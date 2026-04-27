"""
scripts/init_admin.py
初始化首位管理员账号

用法：
  # 命令行传参（推荐）
  docker compose exec api python scripts/init_admin.py admin@example.com YourP@ssw0rd

  # 交互式（不传参数，会提示输入）
  docker compose exec api python scripts/init_admin.py

  # 通过环境变量（CI/CD 友好）
  INIT_ADMIN_EMAIL=admin@x.com INIT_ADMIN_PASSWORD=Pass@123 \
    docker compose exec -e INIT_ADMIN_EMAIL -e INIT_ADMIN_PASSWORD api \
    python scripts/init_admin.py

行为：
  - 如果已有管理员用户，直接退出（幂等）
  - 如果用户已存在但不是管理员，自动提升为管理员
  - 如果用户不存在，创建用户并赋予 admin 角色
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app")

from sqlalchemy import text
from apps.api.core.db import async_session_factory, init_db
from apps.api.modules.auth.service import hash_password


def _check_password_strength(pw: str) -> str | None:
    """返回 None 表示通过，否则返回错误信息。"""
    if len(pw) < 8:
        return "密码至少 8 位"
    import re
    checks = [
        bool(re.search(r'[A-Z]', pw)),
        bool(re.search(r'[a-z]', pw)),
        bool(re.search(r'\d', pw)),
        bool(re.search(r'[^A-Za-z0-9]', pw)),
    ]
    if sum(checks) < 3:
        return "密码须包含大写字母、小写字母、数字、特殊字符中至少三种"
    WEAK = {'password', 'password123', 'Aa123456', 'Abc12345', 'Admin123', 'Qwerty123'}
    if pw.lower() in {w.lower() for w in WEAK}:
        return "密码过于常见，请使用更复杂的密码"
    return None


async def init_admin(email: str, password: str, nickname: str = "管理员") -> None:
    await init_db()

    async with async_session_factory() as session:
        # 1. 检查是否已有管理员
        result = await session.execute(
            text("""
                SELECT COUNT(*) AS cnt FROM user_roles ur
                JOIN roles r ON ur.role_id = r.role_id
                WHERE r.role_name = 'admin'
            """)
        )
        admin_count = result.fetchone().cnt
        if admin_count > 0:
            print(f"✓ 已存在 {admin_count} 个管理员账号，跳过初始化")
            return

        # 2. 检查用户是否已存在
        import uuid
        result = await session.execute(
            text("SELECT user_id, status FROM users WHERE email = :email"),
            {"email": email}
        )
        existing = result.fetchone()

        if existing:
            if existing.status != "active":
                print(f"✗ 用户 {email} 状态为 '{existing.status}'，无法提升为管理员")
                return
            user_id = str(existing.user_id)
            nickname_final = None  # 不覆盖已有昵称
            print(f"→ 用户 {email} 已存在，直接提升为管理员...")
        else:
            user_id = str(uuid.uuid4())
            nickname_final = nickname
            password_hash = hash_password(password)
            await session.execute(
                text("""
                    INSERT INTO users (user_id, email, password_hash, nickname)
                    VALUES (CAST(:uid AS uuid), :email, :pw_hash, :nickname)
                """),
                {"uid": user_id, "email": email, "pw_hash": password_hash, "nickname": nickname_final}
            )
            # 创建学习者画像
            await session.execute(
                text("INSERT INTO learner_profiles (user_id) VALUES (CAST(:uid AS uuid))"),
                {"uid": user_id}
            )
            print(f"✓ 创建用户: {email} (nickname: {nickname_final})")

        # 3. 获取 admin 角色 ID
        result = await session.execute(
            text("SELECT role_id FROM roles WHERE role_name = 'admin'")
        )
        admin_role = result.fetchone()
        if not admin_role:
            print("✗ 数据库中未找到 'admin' 角色，请检查 migrations 是否已执行")
            return

        # 4. 清除现有角色，赋予 admin
        await session.execute(
            text("DELETE FROM user_roles WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id}
        )
        await session.execute(
            text("INSERT INTO user_roles (user_id, role_id) VALUES (CAST(:uid AS uuid), :rid)"),
            {"uid": user_id, "rid": admin_role.role_id}
        )
        await session.commit()

        print(f"✓ 管理员创建成功！")
        print(f"  Email:    {email}")
        print(f"  User ID:  {user_id}")
        if nickname_final:
            print(f"  Nickname: {nickname_final}")
        print(f"  角色:     admin")


def main():
    email = None
    password = None

    # 1) 命令行参数
    if len(sys.argv) >= 3:
        email = sys.argv[1]
        password = sys.argv[2]
    # 2) 环境变量
    elif os.environ.get("INIT_ADMIN_EMAIL") and os.environ.get("INIT_ADMIN_PASSWORD"):
        email = os.environ["INIT_ADMIN_EMAIL"]
        password = os.environ["INIT_ADMIN_PASSWORD"]
        print(f"→ 从环境变量读取: INIT_ADMIN_EMAIL={email}")
    # 3) 交互式输入
    else:
        print("=== 创建首位管理员 ===")
        try:
            email = input("Email: ").strip()
            import getpass
            password = getpass.getpass("Password: ")
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return

    if not email or "@" not in email:
        print("✗ 请输入有效的邮箱地址")
        return

    if not password:
        print("✗ 密码不能为空")
        return

    err = _check_password_strength(password)
    if err:
        print(f"✗ {err}")
        return

    asyncio.run(init_admin(email, password))


if __name__ == "__main__":
    main()
