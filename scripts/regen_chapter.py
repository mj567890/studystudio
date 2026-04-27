"""
单章内容重新生成脚本
用法: docker compose exec api python3 scripts/regen_chapter.py <chapter_id>
"""
import asyncio, os, sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text

CHAPTER_ID = sys.argv[1] if len(sys.argv) > 1 else '7c4c0908-a150-42d0-8608-8fb01c869558'

PROMPT = """为职业技能课程撰写章节正文，严格按结构输出 JSON。

本章：{chapter_title}
目标：{objective}
任务：{task_description}

只输出以下 JSON，不含 markdown 代码块：
{{
  "scene_hook": "100字以内，一个真实职场情境，以'你'开头，引出本章核心问题",
  "skim_summary": "用分号分隔的3条要点，每条不超过20字",
  "full_content": "正文600-900字，含概念/原理/步骤/示例，术语用【名称】标注，在适当位置插入1-2个<!--CHECKPOINT:问题|解析提示-->标记。如涉及编程、命令行或配置操作，正文中关键步骤直接用 <pre><code>代码</code></pre> 包裹内联示例",
  "code_example": "如本章涉及编程、命令行或配置操作，必须提供1个完整可运行的示例（含行内注释说明每步用途），用 <pre><code class=\\"language-python\\">...</code></pre> 格式输出；不涉及编程则填空字符串",
  "misconception_block": "⚠️ 很多人误认为……，实际上……（针对本章常见误解）",
  "prereq_adaptive": {{
    "if_high": "必填。针对已掌握基础的学员，补充一个更深层的技术细节、边界案例或进阶应用场景，100字以内"
  }}
}}"""


async def run():
    engine = create_async_engine(os.environ['DATABASE_URL'], poolclass=NullPool)
    SF = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SF() as s:
        row = (await s.execute(
            text('SELECT title, objective, task_description FROM skill_chapters WHERE chapter_id=CAST(:cid AS uuid)'),
            {'cid': CHAPTER_ID}
        )).fetchone()

    if not row:
        print(f'章节不存在: {CHAPTER_ID}')
        return

    print(f'章节: {row.title}')
    print('正在调用 LLM 生成内容...')

    import apps.api.core.llm_gateway as _gw
    _gw._llm_gateway = None
    from apps.api.core.llm_gateway import get_llm_gateway
    llm = get_llm_gateway()

    prompt = PROMPT.format(
        chapter_title=row.title,
        objective=row.objective or '',
        task_description=row.task_description or '',
    )
    content = await llm.generate(prompt, model_route='tutorial_content')
    print(f'生成完成，长度: {len(content)} 字符')

    async with SF() as s:
        async with s.begin():
            await s.execute(
                text('UPDATE skill_chapters SET content_text=:ct, updated_at=now() WHERE chapter_id=CAST(:cid AS uuid)'),
                {'ct': content.strip(), 'cid': CHAPTER_ID}
            )
    print('已写入 DB，刷新前端查看效果')


asyncio.run(run())
