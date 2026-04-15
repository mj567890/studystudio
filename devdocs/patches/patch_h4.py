"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h4.py
"""
from pathlib import Path

p = Path("apps/api/modules/learner/eight_dim_endpoints.py")
src = p.read_text()

ANCHOR = "# ── D2/D7 主观题 AI 批改"

NEW_ENDPOINT = '''
# ── H-4 遗忘曲线复习提醒 ──────────────────────────────────────────────────

@eight_dim_router.get("/learners/me/review-due")
async def get_review_due(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    返回当前衰减后掌握度 < 0.6 的知识点列表。
    衰减公式：current_score = mastery_score × e^(-decay_rate × days_since)
    """
    import math as _math
    rows = (await db.execute(text("""
        SELECT
            ke.canonical_name,
            ke.domain_tag,
            lks.mastery_score                                              AS original_score,
            lks.decay_rate,
            lks.last_reviewed_at,
            EXTRACT(EPOCH FROM (NOW() - lks.last_reviewed_at)) / 86400.0  AS days_since,
            ROUND((lks.mastery_score * EXP(
                -lks.decay_rate * EXTRACT(EPOCH FROM (NOW() - lks.last_reviewed_at)) / 86400.0
            ))::numeric, 3)                                                AS current_score,
            sc.chapter_id::text   AS chapter_id,
            sc.title              AS chapter_title,
            sb.topic_key
        FROM learner_knowledge_states lks
        JOIN knowledge_entities ke  ON ke.entity_id  = lks.entity_id
        LEFT JOIN chapter_entity_links cel
               ON cel.entity_id = lks.entity_id
        LEFT JOIN skill_chapters sc  ON sc.chapter_id = cel.chapter_id
        LEFT JOIN skill_stages   ss  ON ss.stage_id   = sc.stage_id
        LEFT JOIN skill_blueprints sb
               ON sb.blueprint_id = ss.blueprint_id AND sb.status = 'published'
        WHERE lks.user_id         = CAST(:uid AS uuid)
          AND lks.mastery_score   > 0.1
          AND lks.last_reviewed_at IS NOT NULL
          AND (lks.mastery_score * EXP(
                -lks.decay_rate * EXTRACT(EPOCH FROM (NOW() - lks.last_reviewed_at)) / 86400.0
              )) < 0.6
        ORDER BY current_score ASC
        LIMIT 15
    """), {"uid": current_user["user_id"]})).fetchall()

    seen, items = set(), []
    for r in rows:
        if r.canonical_name in seen:
            continue
        seen.add(r.canonical_name)
        items.append({
            "canonical_name": r.canonical_name,
            "domain_tag":     r.domain_tag,
            "original_score": float(r.original_score),
            "current_score":  float(r.current_score),
            "days_since":     round(float(r.days_since), 1),
            "decay_rate":     float(r.decay_rate),
            "chapter_id":     r.chapter_id,
            "chapter_title":  r.chapter_title,
            "topic_key":      r.topic_key,
        })
    return {"code": 200, "msg": "success", "data": {"items": items, "total": len(items)}}


'''

if "get_review_due" in src:
    print("✗ 端点已存在，跳过写入")
elif ANCHOR not in src:
    print(f"✗ 未找到锚点 '{ANCHOR}'，请手动检查文件")
else:
    p.write_text(src.replace(ANCHOR, NEW_ENDPOINT + ANCHOR))
    print("✓ H-4 端点已写入 eight_dim_endpoints.py")
