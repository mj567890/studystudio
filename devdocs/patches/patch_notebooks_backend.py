from pathlib import Path

p = Path("apps/api/modules/learner/eight_dim_endpoints.py")
s = p.read_text()

NEW = '''
# ── 笔记本 CRUD ───────────────────────────────────────────────────────────

class NotebookCreateRequest(_BM):
    name:      str
    topic_key: str = ""

@eight_dim_router.get("/learners/me/notebooks")
async def list_notebooks(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user["user_id"]
    rows = (await db.execute(text("""
        SELECT nb.notebook_id::text, nb.name, nb.topic_key,
               COUNT(n.note_id) AS note_count
        FROM learner_notebooks nb
        LEFT JOIN learner_notes n
               ON n.notebook_id = nb.notebook_id
        WHERE nb.user_id = CAST(:uid AS uuid)
        GROUP BY nb.notebook_id, nb.name, nb.topic_key
        ORDER BY nb.created_at
    """), {"uid": uid})).fetchall()
    return {"code": 200, "msg": "success", "data": {
        "notebooks": [
            {"notebook_id": r.notebook_id, "name": r.name,
             "topic_key": r.topic_key, "note_count": r.note_count}
            for r in rows
        ]
    }}

@eight_dim_router.post("/learners/me/notebooks")
async def create_notebook(
    req: NotebookCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.name.strip():
        raise HTTPException(400, detail={"code": "NB_001", "msg": "笔记本名称不能为空"})
    uid = current_user["user_id"]
    nid = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO learner_notebooks (notebook_id, user_id, name, topic_key)
        VALUES (CAST(:nid AS uuid), CAST(:uid AS uuid), :name, :tk)
    """), {"nid": nid, "uid": uid, "name": req.name.strip(), "tk": req.topic_key})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"notebook_id": nid, "name": req.name.strip()}}

@eight_dim_router.put("/learners/me/notebooks/{notebook_id}")
async def rename_notebook(
    notebook_id: str,
    req: NotebookCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        UPDATE learner_notebooks SET name = :name
        WHERE notebook_id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)
    """), {"name": req.name.strip(), "nid": notebook_id, "uid": current_user["user_id"]})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}

@eight_dim_router.delete("/learners/me/notebooks/{notebook_id}")
async def delete_notebook(
    notebook_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        DELETE FROM learner_notebooks
        WHERE notebook_id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)
    """), {"nid": notebook_id, "uid": current_user["user_id"]})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}

@eight_dim_router.put("/learners/me/notes/{note_id}/notebook")
async def move_note_to_notebook(
    note_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notebook_id = body.get("notebook_id")
    if notebook_id:
        await db.execute(text("""
            UPDATE learner_notes SET notebook_id = CAST(:nbid AS uuid)
            WHERE note_id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)
        """), {"nbid": notebook_id, "nid": note_id, "uid": current_user["user_id"]})
    else:
        await db.execute(text("""
            UPDATE learner_notes SET notebook_id = NULL
            WHERE note_id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)
        """), {"nid": note_id, "uid": current_user["user_id"]})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}

'''

ANCHOR = "# ── 个人笔记 CRUD"
if "list_notebooks" in s:
    print("✓ 笔记本接口已存在，跳过")
else:
    p.write_text(s.replace(ANCHOR, NEW + ANCHOR, 1))
    print("✓ 笔记本接口写入完成")
