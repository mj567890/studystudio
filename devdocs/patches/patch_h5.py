"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h5.py
"""
from pathlib import Path

p = Path("apps/api/modules/learner/eight_dim_endpoints.py")
src = p.read_text()

ANCHOR = "# ── D2/D7 主观题 AI 批改"

NEW_ENDPOINT = '''
# ── H-5 关联知识推荐 ──────────────────────────────────────────────────────

@eight_dim_router.get("/learners/me/related-recommendations")
async def get_related_recommendations(
    chapter_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    章节完成后的关联知识推荐。
    逻辑：找当前章节的知识点 → 找它们作为 prerequisite_of 解锁的目标知识点
         → 找包含这些目标知识点的章节 → 过滤掉已读的 → 返回 Top 5
    """
    rows = (await db.execute(text("""
        SELECT DISTINCT ON (sc_tgt.chapter_id)
            ke_tgt.canonical_name          AS target_name,
            ke_tgt.short_definition        AS target_def,
            ke_src.canonical_name          AS source_name,
            sc_tgt.chapter_id::text        AS rec_chapter_id,
            sc_tgt.title                   AS rec_chapter_title,
            ss.title                       AS stage_title,
            ss.stage_order,
            sb.topic_key
        FROM chapter_entity_links cel_src
        JOIN knowledge_relations kr
            ON kr.source_entity_id = cel_src.entity_id
           AND kr.relation_type    = 'prerequisite_of'
        JOIN knowledge_entities ke_src ON ke_src.entity_id = cel_src.entity_id
        JOIN knowledge_entities ke_tgt ON ke_tgt.entity_id = kr.target_entity_id
        JOIN chapter_entity_links cel_tgt
            ON cel_tgt.entity_id = kr.target_entity_id
        JOIN skill_chapters sc_tgt
            ON sc_tgt.chapter_id = cel_tgt.chapter_id
        JOIN skill_stages ss
            ON ss.stage_id = sc_tgt.stage_id
        JOIN skill_blueprints sb
            ON sb.blueprint_id = ss.blueprint_id AND sb.status = 'published'
        LEFT JOIN chapter_progress cp
            ON cp.chapter_id = sc_tgt.chapter_id::text
           AND cp.user_id    = CAST(:uid AS uuid)
           AND cp.completed  = true
        WHERE cel_src.chapter_id = CAST(:chapter_id AS uuid)
          AND sc_tgt.chapter_id::text != :chapter_id
          AND cp.chapter_id IS NULL
        ORDER BY sc_tgt.chapter_id, ss.stage_order
        LIMIT 5
    """), {"uid": current_user["user_id"], "chapter_id": chapter_id})).fetchall()

    recs = [
        {
            "chapter_id":    r.rec_chapter_id,
            "chapter_title": r.rec_chapter_title,
            "stage_title":   r.stage_title,
            "topic_key":     r.topic_key,
            "target_name":   r.target_name,
            "target_def":    r.target_def or "",
            "source_name":   r.source_name,
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"recommendations": recs}}


'''

if "get_related_recommendations" in src:
    print("✓ H-5 端点已存在，跳过")
elif ANCHOR not in src:
    print(f"✗ 未找到锚点，请检查文件")
else:
    p.write_text(src.replace(ANCHOR, NEW_ENDPOINT + ANCHOR))
    print("✓ H-5 端点已写入 eight_dim_endpoints.py")
