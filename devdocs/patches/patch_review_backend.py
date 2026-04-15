from pathlib import Path

p = Path("apps/api/modules/learner/eight_dim_endpoints.py")
s = p.read_text()

NEW = '''
# ── 复习提醒 ─────────────────────────────────────────────────────────────

REVIEW_INTERVALS = [1, 3, 7, 14, 30]  # 天数

@eight_dim_router.get("/learners/me/notes/due-review")
async def get_due_reviews(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import json as _j
    uid = current_user["user_id"]
    rows = (await db.execute(text("""
        SELECT note_id::text, title, content, review_count,
               next_review_at, last_reviewed_at, tags,
               chapter_title, notebook_id::text
        FROM learner_notes
        WHERE user_id = CAST(:uid AS uuid)
          AND (
            next_review_at IS NULL AND created_at <= NOW() - INTERVAL '1 day'
            OR next_review_at <= NOW()
          )
        ORDER BY COALESCE(next_review_at, created_at)
        LIMIT 50
    """), {"uid": uid})).fetchall()

    total_due = (await db.execute(text("""
        SELECT COUNT(*) FROM learner_notes
        WHERE user_id = CAST(:uid AS uuid)
          AND (
            next_review_at IS NULL AND created_at <= NOW() - INTERVAL '1 day'
            OR next_review_at <= NOW()
          )
    """), {"uid": uid})).scalar()

    notes = [
        {
            "note_id":        r.note_id,
            "title":          r.title,
            "content":        r.content,
            "review_count":   r.review_count,
            "next_review_at": r.next_review_at.isoformat() if r.next_review_at else None,
            "last_reviewed_at": r.last_reviewed_at.isoformat() if r.last_reviewed_at else None,
            "tags":           r.tags if isinstance(r.tags, list) else _j.loads(r.tags or "[]"),
            "chapter_title":  r.chapter_title,
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {
        "notes": notes,
        "total_due": total_due,
    }}


@eight_dim_router.post("/learners/me/notes/{note_id}/reviewed")
async def mark_reviewed(
    note_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timedelta
    uid = current_user["user_id"]
    row = (await db.execute(text("""
        SELECT review_count FROM learner_notes
        WHERE note_id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)
    """), {"nid": note_id, "uid": uid})).fetchone()

    if not row:
        raise HTTPException(404, detail={"msg": "笔记不存在"})

    count = row.review_count + 1
    interval = REVIEW_INTERVALS[min(count - 1, len(REVIEW_INTERVALS) - 1)]
    next_review = datetime.utcnow() + timedelta(days=interval)

    await db.execute(text("""
        UPDATE learner_notes
        SET review_count = :count,
            last_reviewed_at = NOW(),
            next_review_at = :next_review
        WHERE note_id = CAST(:nid AS uuid) AND user_id = CAST(:uid AS uuid)
    """), {"count": count, "next_review": next_review, "nid": note_id, "uid": uid})
    await db.commit()

    return {"code": 200, "msg": "success", "data": {
        "review_count": count,
        "next_review_at": next_review.isoformat(),
        "next_interval_days": interval,
    }}

'''

ANCHOR = "# ── AI 合并笔记"
if "due-review" in s:
    print("✓ 复习接口已存在，跳过")
else:
    p.write_text(s.replace(ANCHOR, NEW + ANCHOR, 1))
    print("✓ 复习接口写入完成")
