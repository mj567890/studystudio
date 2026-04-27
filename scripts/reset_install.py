#!/usr/bin/env python3
"""
scripts/reset_install.py — 重置系统到未安装状态（开发调试用）

用法：
  docker compose exec api python scripts/reset_install.py
  docker compose exec api python scripts/reset_install.py --force   # 跳过确认
"""
import asyncio
import sys
import os
sys.path.insert(0, "/app")

from sqlalchemy import text
from apps.api.core.db import async_session_factory, init_db


async def reset(force: bool = False):
    if not force:
        print("⚠️  即将删除所有用户数据并重置系统为未安装状态！")
        resp = input("确认？(yes/no): ").strip().lower()
        if resp != "yes":
            print("已取消")
            return

    await init_db()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM user_roles"))
            await session.execute(text("DELETE FROM learner_profiles"))
            await session.execute(text("DELETE FROM users"))
            await session.execute(
                text("UPDATE system_configs SET config_value='false' WHERE config_key='init_completed'")
            )
            await session.execute(
                text("UPDATE system_configs SET config_value='' WHERE config_key IN ('site_name','site_copyright','registration_agreement')")
            )
    print("✓ 已重置为未安装状态，访问 http://localhost:3000 将跳转到安装向导")


if __name__ == "__main__":
    asyncio.run(reset("--force" in sys.argv))
