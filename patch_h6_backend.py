"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h6_backend.py
"""
from pathlib import Path

errors = []

def patch(content, anchor, new_text, mode="replace"):
    if anchor not in content:
        errors.append(f"  ✗ 未找到锚点: {repr(anchor[:60])}")
        return content
    if mode == "prepend":
        return content.replace(anchor, new_text + anchor, 1)
    return content.replace(anchor, new_text, 1)


# ════════════════════════════════════════════════════════════════
# 1. learner_service.py — mark_chapter_progress 接受 duration_seconds
# ════════════════════════════════════════════════════════════════
p1 = Path("apps/api/modules/learner/learner_service.py")
s1 = p1.read_text()

# MarkChapterRequest 加字段
s1 = patch(s1,
    "class MarkChapterRequest(BaseModel):",
    """class MarkChapterRequest(BaseModel):
    duration_seconds: int = 0""",
)
# 注：实际 Request 可能在 router 文件，下面同步修改

# INSERT 语句加 duration_seconds 列
s1 = patch(s1,
    "INSERT INTO chapter_progress\n              (id, user_id, tutorial_id, chapter_id, completed, completed_at)",
    "INSERT INTO chapter_progress\n              (id, user_id, tutorial_id, chapter_id, completed, completed_at, duration_seconds)",
)
s1 = patch(s1,
    "(:id, :uid, :tid, :cid, :completed,\n               CASE WHEN :completed THEN NOW() ELSE NULL END)",
    "(:id, :uid, :tid, :cid, :completed,\n               CASE WHEN :completed THEN NOW() ELSE NULL END,\n               :duration_seconds)",
)
# ON CONFLICT 加 duration
s1 = patch(s1,
    "DO UPDATE SET\n              completed    = EXCLUDED.completed,\n              completed_at = CASE WHEN EXCLUDED.completed THEN NOW() ELSE NULL END",
    "DO UPDATE SET\n              completed         = EXCLUDED.completed,\n              completed_at      = CASE WHEN EXCLUDED.completed THEN NOW() ELSE NULL END,\n              duration_seconds  = GREATEST(chapter_progress.duration_seconds, EXCLUDED.duration_seconds)",
)
# 传参加 duration_seconds
s1 = patch(s1,
    '"completed": req.completed,',
    '"completed": req.completed,\n            "duration_seconds": getattr(req, "duration_seconds", 0),',
)

p1.write_text(s1)


# ════════════════════════════════════════════════════════════════
# 2. eight_dim_endpoints.py — 错题记录 + error-patterns 接口
# ════════════════════════════════════════════════════════════════
p2 = Path("apps/api/modules/learner/eight_dim_endpoints.py")
s2 = p2.read_text()

ANCHOR = "# ── D2/D7 主观题 AI 批改"

NEW_ENDPOINTS = '''
# ── H-6 学习行为埋点：错题模式查询 ──────────────────────────────────────

@eight_dim_router.get("/learners/me/error-patterns")
async def get_error_patterns(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    聚合用户近期错题，按知识点实体统计错误频次，
    返回 Top 10 弱点知识点及所在章节。
    """
    rows = (await db.execute(text("""
        SELECT
            ke.canonical_name,
            ke.domain_tag,
            ke.short_definition,
            COUNT(*)                AS wrong_count,
            MAX(cqa.attempted_at)   AS last_wrong_at,
            sc.title                AS chapter_title,
            sc.chapter_id::text     AS chapter_id
        FROM chapter_quiz_attempts cqa
        CROSS JOIN LATERAL jsonb_array_elements_text(cqa.wrong_entity_ids) AS eid
        JOIN knowledge_entities ke ON ke.entity_id = CAST(eid AS uuid)
        LEFT JOIN chapter_entity_links cel ON cel.entity_id = ke.entity_id
        LEFT JOIN skill_chapters sc ON sc.chapter_id = cel.chapter_id
        WHERE cqa.user_id = CAST(:uid AS uuid)
          AND cqa.attempted_at >= NOW() - INTERVAL '30 days'
        GROUP BY ke.entity_id, ke.canonical_name, ke.domain_tag,
                 ke.short_definition, sc.title, sc.chapter_id
        ORDER BY wrong_count DESC
        LIMIT 10
    """), {"uid": current_user["user_id"]})).fetchall()

    patterns = [
        {
            "canonical_name": r.canonical_name,
            "domain_tag":     r.domain_tag,
            "short_def":      r.short_definition or "",
            "wrong_count":    r.wrong_count,
            "last_wrong_at":  r.last_wrong_at.isoformat() if r.last_wrong_at else None,
            "chapter_title":  r.chapter_title,
            "chapter_id":     r.chapter_id,
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"patterns": patterns}}


'''

if "get_error_patterns" in s2:
    print("✓ error-patterns 端点已存在，跳过")
else:
    s2 = patch(s2, ANCHOR, NEW_ENDPOINTS + ANCHOR, "replace")
    p2.write_text(s2)
    print("✓ error-patterns 端点已写入")


# ════════════════════════════════════════════════════════════════
# 3. learner_service.py（或同文件）— submit_chapter_quiz 写入错题记录
# ════════════════════════════════════════════════════════════════
# 找 submit_chapter_quiz，在 await db.commit() 前写入 chapter_quiz_attempts
TARGET_FILE = None
for candidate in [
    "apps/api/modules/learner/learner_service.py",
    "apps/api/modules/learner/eight_dim_endpoints.py",
]:
    cp = Path(candidate)
    if "submit_chapter_quiz" in cp.read_text():
        TARGET_FILE = cp
        break

if TARGET_FILE:
    s3 = TARGET_FILE.read_text()
    OLD_COMMIT = """    await db.commit()

    correct = sum(1 for a in req.answers if a.is_correct)
    total   = len(req.answers)
    score   = round(correct / total * 100) if total else 0"""

    NEW_COMMIT = """    correct = sum(1 for a in req.answers if a.is_correct)
    total   = len(req.answers)
    score   = round(correct / total * 100) if total else 0

    # H-6 埋点：记录错题实体
    import json as _json2, uuid as _uuid2
    wrong_ids = [a.entity_id for a in req.answers if not a.is_correct and getattr(a, "entity_id", None)]
    await db.execute(
        _text(\"\"\"
            INSERT INTO chapter_quiz_attempts
              (id, user_id, chapter_id, score, correct_count, total_count, wrong_entity_ids)
            VALUES
              (CAST(:id AS uuid), CAST(:uid AS uuid), :cid,
               :score, :correct, :total, CAST(:wrong AS jsonb))
        \"\"\"),
        {"id": str(_uuid2.uuid4()), "uid": user_id,
         "cid": req.chapter_id, "score": score,
         "correct": correct, "total": total,
         "wrong": _json2.dumps(wrong_ids)}
    )
    await db.commit()"""

    if OLD_COMMIT in s3:
        TARGET_FILE.write_text(s3.replace(OLD_COMMIT, NEW_COMMIT, 1))
        print(f"✓ 错题埋点写入 {TARGET_FILE}")
    else:
        print(f"✗ 未找到 submit_chapter_quiz 的 commit 锚点，请手动处理")
else:
    print("✗ 未找到 submit_chapter_quiz 所在文件")


if errors:
    print("\n以下锚点未找到（可能已应用或格式不同）：")
    for e in errors:
        print(e)
else:
    print("\n✓ 所有后端补丁应用完成")
