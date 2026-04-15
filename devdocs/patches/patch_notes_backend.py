"""
在服务器 ~/studystudio 目录下执行：
python3 patch_notes_backend.py
"""
from pathlib import Path

# ════════════════════════════════════════════════════════════════
# eight_dim_endpoints.py — 笔记 CRUD + 对话重命名
# ════════════════════════════════════════════════════════════════
p = Path("apps/api/modules/learner/eight_dim_endpoints.py")
s = p.read_text()

ANCHOR = "# ── D2/D7 主观题 AI 批改"

NEW_CODE = '''
# ── 个人笔记 CRUD ─────────────────────────────────────────────────────────

from pydantic import BaseModel as _BM

class NoteCreateRequest(_BM):
    title:           str = ""
    content:         str
    source_type:     str = "manual"   # manual | ai_chat
    topic_key:       str = ""
    chapter_id:      str = ""
    chapter_title:   str = ""
    conversation_id: str = ""
    tags:            list[str] = []

class NoteUpdateRequest(_BM):
    title:   str | None = None
    content: str | None = None
    tags:    list[str] | None = None


@eight_dim_router.get("/learners/me/notes")
async def list_notes(
    topic_key: str = "",
    keyword:   str = "",
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import json as _j
    uid = current_user["user_id"]
    sql = """
        SELECT note_id::text, title, content, source_type,
               topic_key, chapter_id, chapter_title, conversation_id,
               tags, created_at, updated_at
        FROM learner_notes
        WHERE user_id = CAST(:uid AS uuid)
          AND (:tk = '' OR topic_key = :tk)
          AND (:kw = '' OR title ILIKE :kw_like OR content ILIKE :kw_like)
        ORDER BY updated_at DESC
        LIMIT 100
    """
    rows = (await db.execute(text(sql), {
        "uid": uid, "tk": topic_key,
        "kw": keyword, "kw_like": f"%{keyword}%",
    })).fetchall()
    notes = [
        {
            "note_id":        r.note_id,
            "title":          r.title,
            "content":        r.content,
            "source_type":    r.source_type,
            "topic_key":      r.topic_key,
            "chapter_id":     r.chapter_id,
            "chapter_title":  r.chapter_title,
            "conversation_id": r.conversation_id,
            "tags":           r.tags if isinstance(r.tags, list) else _j.loads(r.tags or "[]"),
            "created_at":     r.created_at.isoformat() if r.created_at else "",
            "updated_at":     r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"notes": notes, "total": len(notes)}}


@eight_dim_router.post("/learners/me/notes")
async def create_note(
    req: NoteCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import json as _j2
    if not req.content.strip():
        raise HTTPException(400, detail={"code": "NOTE_001", "msg": "笔记内容不能为空"})
    uid = current_user["user_id"]
    title = req.title.strip() or req.content[:30].replace("\\n", " ")
    nid = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO learner_notes
          (note_id, user_id, title, content, source_type,
           topic_key, chapter_id, chapter_title, conversation_id, tags)
        VALUES
          (CAST(:nid AS uuid), CAST(:uid AS uuid), :title, :content, :stype,
           :tk, :cid, :ctitle, :conv, CAST(:tags AS jsonb))
    """), {
        "nid": nid, "uid": uid, "title": title,
        "content": req.content, "stype": req.source_type,
        "tk": req.topic_key, "cid": req.chapter_id,
        "ctitle": req.chapter_title, "conv": req.conversation_id,
        "tags": _j2.dumps(req.tags, ensure_ascii=False),
    })
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"note_id": nid, "title": title}}


@eight_dim_router.put("/learners/me/notes/{note_id}")
async def update_note(
    note_id: str,
    req: NoteUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import json as _j3
    uid = current_user["user_id"]
    sets, params = [], {"uid": uid, "nid": note_id}
    if req.title is not None:
        sets.append("title = :title"); params["title"] = req.title
    if req.content is not None:
        sets.append("content = :content"); params["content"] = req.content
    if req.tags is not None:
        sets.append("tags = CAST(:tags AS jsonb)")
        params["tags"] = _j3.dumps(req.tags, ensure_ascii=False)
    if not sets:
        return {"code": 200, "msg": "success", "data": {}}
    sets.append("updated_at = NOW()")
    await db.execute(text(f"""
        UPDATE learner_notes SET {", ".join(sets)}
        WHERE note_id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)
    """), params)
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}


@eight_dim_router.delete("/learners/me/notes/{note_id}")
async def delete_note(
    note_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        DELETE FROM learner_notes
        WHERE note_id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)
    """), {"nid": note_id, "uid": current_user["user_id"]})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}


# ── 对话重命名 ────────────────────────────────────────────────────────────

class ConvRenameRequest(_BM):
    title: str

@eight_dim_router.put("/teaching/conversations/{conversation_id}/title")
async def rename_conversation(
    conversation_id: str,
    req: ConvRenameRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.title.strip():
        raise HTTPException(400, detail={"code": "CONV_001", "msg": "标题不能为空"})
    await db.execute(text("""
        UPDATE conversations SET title = :title
        WHERE conversation_id = CAST(:cid AS uuid)
          AND user_id = CAST(:uid AS uuid)
    """), {
        "title": req.title.strip(),
        "cid": conversation_id,
        "uid": current_user["user_id"],
    })
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}


'''

if "list_notes" in s:
    print("✓ 笔记接口已存在，跳过")
else:
    p.write_text(s.replace(ANCHOR, NEW_CODE + ANCHOR, 1))
    print("✓ 笔记接口写入完成")
