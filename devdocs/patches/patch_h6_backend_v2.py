"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h6_backend_v2.py
"""
from pathlib import Path

errors = []

def patch(content, anchor, new_text, mode="replace"):
    if anchor not in content:
        errors.append(f"  ✗ 未找到锚点: {repr(anchor[:70])}")
        return content
    if mode == "prepend":
        return content.replace(anchor, new_text + anchor, 1)
    return content.replace(anchor, new_text, 1)


# ════════════════════════════════════════════════════════════════
# routers.py — ChapterProgressRequest 加 duration_seconds
# ════════════════════════════════════════════════════════════════
p = Path("apps/api/modules/routers.py")
s = p.read_text()

# 加字段（锚在 completed 字段末尾 + 两个空行 + 路由装饰器）
s = patch(s,
    "    completed:   bool\n\n\n@learner_router.post(\"/chapter-progress\")",
    "    completed:        bool\n    duration_seconds: int = 0\n\n\n@learner_router.post(\"/chapter-progress\")",
)

# INSERT 加列
s = patch(s,
    "INSERT INTO chapter_progress\n              (user_id, tutorial_id, chapter_id, completed, completed_at)\n            VALUES\n              (:uid, :tid, :chid, :done, CASE WHEN :done THEN NOW() ELSE NULL END)\n            ON CONFLICT (user_id, tutorial_id, chapter_id)\n            DO UPDATE SET\n              completed    = EXCLUDED.completed,\n              completed_at = EXCLUDED.completed_at",
    "INSERT INTO chapter_progress\n              (user_id, tutorial_id, chapter_id, completed, completed_at, duration_seconds)\n            VALUES\n              (:uid, :tid, :chid, :done, CASE WHEN :done THEN NOW() ELSE NULL END, :dur)\n            ON CONFLICT (user_id, tutorial_id, chapter_id)\n            DO UPDATE SET\n              completed        = EXCLUDED.completed,\n              completed_at     = EXCLUDED.completed_at,\n              duration_seconds = GREATEST(chapter_progress.duration_seconds, EXCLUDED.duration_seconds)",
)

# 传参加 duration_seconds
s = patch(s,
    '            "uid":  current_user["user_id"],\n            "tid":  req.tutorial_id,\n            "chid": req.chapter_id,\n            "done": req.completed,',
    '            "uid":  current_user["user_id"],\n            "tid":  req.tutorial_id,\n            "chid": req.chapter_id,\n            "done": req.completed,\n            "dur":  getattr(req, "duration_seconds", 0),',
)

# submit_chapter_quiz — 在 await db.commit() 前插入错题埋点
s = patch(s,
    "    await db.commit()\n\n    correct = sum(1 for a in req.answers if a.is_correct)\n    total   = len(req.answers)\n    score   = round(correct / total * 100) if total else 0\n\n    return {\n        \"code\": 200, \"msg\": \"success\",",
    """    correct = sum(1 for a in req.answers if a.is_correct)
    total   = len(req.answers)
    score   = round(correct / total * 100) if total else 0

    # H-6 埋点：记录错题实体
    import json as _json_h6, uuid as _uuid_h6
    wrong_ids = [str(a.entity_id) for a in req.answers
                 if not a.is_correct and getattr(a, "entity_id", None)]
    await db.execute(
        _text(\"\"\"
            INSERT INTO chapter_quiz_attempts
              (id, user_id, chapter_id, score, correct_count, total_count, wrong_entity_ids)
            VALUES
              (gen_random_uuid(), CAST(:uid AS uuid), :cid,
               :score, :correct, :total, CAST(:wrong AS jsonb))
        \"\"\"),
        {"uid": user_id, "cid": req.chapter_id, "score": score,
         "correct": correct, "total": total,
         "wrong": _json_h6.dumps(wrong_ids)}
    )
    await db.commit()

    return {
        "code": 200, "msg": "success",""",
)

p.write_text(s)
print("✓ routers.py 补丁完成")

if errors:
    print("\n未找到的锚点：")
    for e in errors: print(e)
    errors.clear()


# ════════════════════════════════════════════════════════════════
# admin/router.py — MarkChapterRequest 加 duration_seconds（兼容）
# ════════════════════════════════════════════════════════════════
p2 = Path("apps/api/modules/admin/router.py")
s2 = p2.read_text()

s2 = patch(s2,
    "class MarkChapterRequest(BaseModel):\n    tutorial_id: str\n    chapter_id:  str\n    completed:   bool = True",
    "class MarkChapterRequest(BaseModel):\n    tutorial_id:      str\n    chapter_id:       str\n    completed:        bool = True\n    duration_seconds: int  = 0",
)

p2.write_text(s2)
print("✓ admin/router.py 补丁完成")

if errors:
    print("\n未找到的锚点：")
    for e in errors: print(e)
