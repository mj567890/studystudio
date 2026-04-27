from pathlib import Path

p = Path("apps/api/modules/learner/eight_dim_endpoints.py")
s = p.read_text()

NEW = '''
# ── AI 合并笔记 ───────────────────────────────────────────────────────────

class NoteMergeRequest(_BM):
    note_ids:    list[str]
    notebook_id: str = ""

@eight_dim_router.post("/learners/me/notes/ai-merge")
async def ai_merge_notes(
    req: NoteMergeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(req.note_ids) < 2:
        raise HTTPException(400, detail={"code": "MERGE_001", "msg": "至少选择 2 条笔记"})
    uid = current_user["user_id"]

    placeholders = ", ".join([f"CAST(:id{i} AS uuid)" for i in range(len(req.note_ids))])
    params = {"uid": uid}
    for i, nid in enumerate(req.note_ids):
        params[f"id{i}"] = nid

    rows = (await db.execute(text(f"""
        SELECT title, content FROM learner_notes
        WHERE note_id IN ({placeholders})
          AND user_id = CAST(:uid AS uuid)
        ORDER BY created_at
    """), params)).fetchall()

    if not rows:
        raise HTTPException(404, detail={"code": "MERGE_002", "msg": "笔记不存在"})

    fragments = "\\n\\n---\\n\\n".join(
        f"【{r.title or '无标题'}】\\n{r.content}" for r in rows
    )

    from apps.api.core.llm_gateway import LLMGateway
    gw = LLMGateway()
    prompt = f"""你是一位学习助手。请将以下多条碎片笔记整合成一篇结构清晰、逻辑连贯的学习笔记。

要求：
1. 提炼核心知识点，去除重复内容
2. 用清晰的标题和段落组织内容
3. 保留重要细节和例子
4. 输出格式：先给出一个简洁的标题（一行），然后是正文内容

碎片笔记如下：
{fragments}"""

    result = await gw.complete(prompt, max_tokens=2000)
    lines = result.strip().split("\\n", 1)
    title = lines[0].lstrip("#").strip() if lines else "AI 整理笔记"
    content = lines[1].strip() if len(lines) > 1 else result.strip()

    return {"code": 200, "msg": "success", "data": {
        "title":   title,
        "content": content,
    }}

'''

ANCHOR = "# ── 笔记本 CRUD"
if "ai_merge_notes" in s:
    print("✓ AI 合并接口已存在，跳过")
else:
    p.write_text(s.replace(ANCHOR, NEW + ANCHOR, 1))
    print("✓ AI 合并接口写入完成")
