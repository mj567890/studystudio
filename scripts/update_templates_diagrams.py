"""
更新课程模板：为每个系统模板追加「图表要求」章节
通过 Docker exec 在 API 容器中执行
"""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql+asyncpg://user:pass@postgres:5432/adaptive_learning"

# 各模板的图表要求追加内容
DIAGRAM_SECTIONS = {
    "系统默认": """
【图表要求】
如本章涉及系统架构、数据流程或组件交互关系，在 JSON 输出的 diagrams 数组中生成 1-2 个 Mermaid 图表。
- 架构类内容用 graph TD 展示组件层级和调用关系
- 流程类内容用 flowchart LR 展示操作步骤和分支
- 不适宜用图表说明的内容则不生成 diagrams""",

    "快速上手": """
【图表要求】
如本章涉及系统架构、数据流或组件交互，在 JSON 输出的 diagrams 数组中生成 1-2 个 Mermaid 图表。
- 系统架构用 graph TD 展示组件关系
- 操作流程用 flowchart LR 展示步骤顺序
- 纯理论或纯概念内容可不生成""",

    "实操导向": """
【图表要求】
如本章涉及系统部署架构、任务执行流程或数据管道，在 JSON 输出的 diagrams 数组中生成 1-2 个 Mermaid 图表。
- 部署/网络架构用 graph TD 展示拓扑和连接关系
- 操作步骤用 flowchart LR 展示任务执行流程
- 无架构或流程内容的章节可不生成""",

    "理论基础": """
【图表要求】
如本章涉及概念体系、机制模型或对比关系，在 JSON 输出的 diagrams 数组中生成 1-3 个 Mermaid 图表。
- 概念体系用 graph TD 展示层级和关联关系
- 时序/交互用 sequenceDiagram 展示组件间消息传递
- 对比分类用 graph LR 展示差异和分支
- 图表应增强理论理解，而非替代文字说明""",

    "速成精简": """
【图表要求】
仅在架构或流程比纯文字描述更高效时，在 JSON 输出的 diagrams 数组中生成至多 1 个 Mermaid 图表。
- 用最简 graph TD/LR 展示核心关系，节点不超过 5 个
- 大多数章节不需要图表""",
}


async def main():
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        for name, diagram_section in DIAGRAM_SECTIONS.items():
            # 取出当前 content
            result = await session.execute(
                text("SELECT content FROM course_templates WHERE name = :name AND is_system = true"),
                {"name": name},
            )
            row = result.fetchone()
            if not row:
                print(f"SKIP: template '{name}' not found")
                continue

            current_content = row.content
            # 检查是否已经包含图表要求
            if "【图表要求】" in current_content:
                print(f"SKIP: '{name}' already has 图表要求 section")
                continue

            # 在【教学风格】之前插入图表要求
            new_content = current_content.replace(
                "【教学风格】",
                diagram_section.strip() + "\n\n【教学风格】",
            )
            if new_content == current_content:
                # 如果没找到【教学风格】，追加到末尾
                new_content = current_content.rstrip() + "\n\n" + diagram_section.strip()

            await session.execute(
                text("UPDATE course_templates SET content = :content, updated_at = now() WHERE name = :name AND is_system = true"),
                {"name": name, "content": new_content},
            )
            print(f"UPDATED: '{name}' (+{len(new_content) - len(current_content)} chars)")

        await session.commit()
        print("Done.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
