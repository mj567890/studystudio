"""
scripts/prebuild_banks.py
冷启动题库预生成脚本

用途：为所有已有主题预生成定位自检题库，
     用户首次进入主题时直接读缓存，无需等待 LLM 实时生成。
运行：docker compose exec api python /app/scripts/prebuild_banks.py
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from apps.api.tasks.tutorial_tasks import prebuild_placement_bank
from sqlalchemy import text
from apps.api.core.db import async_session_factory, init_db


async def get_all_topic_keys() -> list[str]:
    """从知识库中获取所有存在的领域标签作为主题key。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("""
                SELECT DISTINCT domain_tag
                FROM knowledge_entities
                WHERE review_status = 'approved'
                ORDER BY domain_tag
            """)
        )
        return [row.domain_tag for row in result.fetchall()]


async def main():
    print("🔧 开始预生成冷启动题库...")

    await init_db()

    topic_keys = await get_all_topic_keys()

    if not topic_keys:
        print("⚠️  知识库为空，请先运行 seed_knowledge.py 导入知识点")
        print("   docker compose exec api python /app/scripts/seed_knowledge.py")
        return

    print(f"   发现 {len(topic_keys)} 个主题：{', '.join(topic_keys)}")
    print("   正在触发后台任务（Celery 异步执行）...\n")

    for topic_key in topic_keys:
        # 触发 Celery 异步任务
        prebuild_placement_bank.delay(topic_key)
        print(f"  ✅ 已触发：{topic_key}")

    print(f"\n🎉 共触发 {len(topic_keys)} 个题库生成任务")
    print("   任务在后台异步执行，通常需要 1-3 分钟完成")
    print("   可通过以下命令查看任务进度：")
    print("   docker compose logs celery_worker -f")


if __name__ == "__main__":
    asyncio.run(main())
