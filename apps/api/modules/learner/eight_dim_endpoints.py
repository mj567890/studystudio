"""
apps/api/modules/learner/eight_dim_endpoints.py
八维度学习增强系统 — 新增 API 端点
"""
from __future__ import annotations
import json, uuid, re as _re
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.db import get_db
from apps.api.core.llm_gateway import get_llm_gateway
from apps.api.modules.auth.router import get_current_user

logger = structlog.get_logger(__name__)
eight_dim_router = APIRouter(prefix="/api", tags=["eight-dimensions"])


# ── D6 学习节奏偏好 ───────────────────────────────────────────────────────

@eight_dim_router.get("/learners/me/learning-mode")
async def get_learning_mode(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT read_mode FROM learner_learning_mode WHERE user_id=CAST(:uid AS uuid)"),
        {"uid": current_user["user_id"]},
    )).fetchone()
    return {"code": 200, "msg": "success", "data": {"read_mode": row.read_mode if row else "normal"}}


class LearningModeRequest(BaseModel):
    read_mode: str


@eight_dim_router.post("/learners/me/learning-mode")
async def set_learning_mode(
    req: LearningModeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.read_mode not in ("skim", "normal", "deep"):
        raise HTTPException(400, detail={"code": "DIM_001", "msg": "read_mode须为skim/normal/deep"})
    await db.execute(text("""
        INSERT INTO learner_learning_mode (user_id, read_mode, updated_at)
        VALUES (CAST(:uid AS uuid), :mode, now())
        ON CONFLICT (user_id) DO UPDATE SET read_mode=:mode, updated_at=now()
    """), {"uid": current_user["user_id"], "mode": req.read_mode})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"read_mode": req.read_mode}}


# ── D7 章末反思 ───────────────────────────────────────────────────────────

_REFLECT_PROMPT = (
    "你是教学反思评估专家。\n"
    "知识点：{entities}\n"
    "章节要点：{summary}\n"
    "学员解释：{answer}\n\n"
    "输出JSON（不含markdown）：\n"
    '{{"score":0.8,"strengths":"理解正确处",'
    '"gaps":"遗漏偏差","suggestion":"改进建议","corrected_example":"修正写法"}}\n'
    "score范围0-1。"
)


class ReflectRequest(BaseModel):
    chapter_id: str
    own_example: str
    misconception: str = ""


@eight_dim_router.post("/learners/me/reflect")
async def submit_reflection(
    req: ReflectRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user["user_id"]
    ents = (await db.execute(text("""
        SELECT ke.canonical_name
        FROM chapter_entity_links cel
        JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
        WHERE cel.chapter_id = :cid LIMIT 8
    """), {"cid": req.chapter_id})).fetchall()
    entities_text = ", ".join(r.canonical_name for r in ents)
    ch = (await db.execute(
        text("SELECT title, content_text FROM skill_chapters WHERE chapter_id::text=:cid LIMIT 1"),
        {"cid": req.chapter_id},
    )).fetchone()
    summary = ""
    if ch:
        try:
            p = json.loads(ch.content_text or "")
            s = p.get("skim_summary", "")
            summary = " / ".join(s) if isinstance(s, list) else str(s)
        except Exception:
            summary = (ch.content_text or "")[:150]
    llm = get_llm_gateway()
    fb = {"score": 0.5, "strengths": "已记录", "gaps": "", "suggestion": "", "corrected_example": ""}
    score = 0.5
    try:
        raw = await llm.generate(
            _REFLECT_PROMPT.format(
                entities=entities_text or "（暂无）",
                summary=summary or (ch.title if ch else req.chapter_id),
                answer=req.own_example,
            ),
            model_route="simple",
        )
        clean = raw.replace("```json", "").replace("```", "").strip()
        m = _re.search(r"\{.*\}", clean, _re.DOTALL)
        if m:
            fb = json.loads(m.group())
            score = float(fb.get("score", 0.5))
    except Exception as e:
        logger.warning("reflect grading failed", error=str(e))
    await db.execute(text("""
        INSERT INTO chapter_reflections
          (user_id, chapter_id, own_example, misconception, ai_feedback, ai_score, updated_at)
        VALUES (CAST(:uid AS uuid), :cid, :ex, :mis, CAST(:fb AS jsonb), :score, now())
        ON CONFLICT (user_id, chapter_id) DO UPDATE SET
          own_example=EXCLUDED.own_example, misconception=EXCLUDED.misconception,
          ai_feedback=EXCLUDED.ai_feedback, ai_score=EXCLUDED.ai_score, updated_at=now()
    """), {"uid": uid, "cid": req.chapter_id, "ex": req.own_example,
           "mis": req.misconception, "fb": json.dumps(fb, ensure_ascii=False), "score": score})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"ai_feedback": fb, "ai_score": score}}


@eight_dim_router.get("/learners/me/reflect/{chapter_id}")
async def get_reflection(
    chapter_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(text("""
        SELECT own_example, misconception, ai_feedback, ai_score, updated_at
        FROM chapter_reflections
        WHERE user_id=CAST(:uid AS uuid) AND chapter_id=:cid
    """), {"uid": current_user["user_id"], "cid": chapter_id})).fetchone()
    if not row:
        return {"code": 200, "msg": "success", "data": None}
    return {"code": 200, "msg": "success", "data": {
        "own_example":   row.own_example,
        "misconception": row.misconception,
        "ai_feedback":   row.ai_feedback,
        "ai_score":      float(row.ai_score) if row.ai_score else None,
        "updated_at":    row.updated_at.isoformat() if row.updated_at else None,
    }}


# ── D4 社区笔记 ───────────────────────────────────────────────────────────

class SocialNoteRequest(BaseModel):
    tutorial_id: str
    chapter_id: str
    note_type: str = "tip"
    content: str
    is_public: bool = True


@eight_dim_router.get("/tutorials/social-notes/{chapter_id}")
async def get_social_notes(
    chapter_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(text("""
        SELECT ta.annotation_id::text AS aid, ta.note_type, ta.gap_types AS content,
               ta.likes, ta.user_id::text AS uid, u.nickname, ta.created_at
        FROM tutorial_annotations ta
        JOIN users u ON u.user_id = ta.user_id
        WHERE ta.chapter_id=:cid AND ta.is_public=true
          AND ta.note_type IN ('stuck','tip','ai_summary')
        ORDER BY ta.likes DESC, ta.created_at DESC LIMIT 20
    """), {"cid": chapter_id})
    me = current_user["user_id"]
    notes = [{"id": r.aid, "note_type": r.note_type, "content": r.content,
               "likes": r.likes, "is_mine": r.uid == me,
               "nickname": r.nickname or "匿名学员",
               "created_at": r.created_at.isoformat() if r.created_at else ""}
             for r in result.fetchall()]
    return {"code": 200, "msg": "success", "data": {"notes": notes}}


@eight_dim_router.post("/tutorials/social-notes")
async def post_social_note(
    req: SocialNoteRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.note_type not in ("stuck", "tip"):
        raise HTTPException(400, detail={"code": "DIM_002", "msg": "note_type须为stuck/tip"})
    if len(req.content.strip()) < 5:
        raise HTTPException(400, detail={"code": "DIM_003", "msg": "内容太短"})
    nid = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO tutorial_annotations
          (annotation_id, user_id, tutorial_id, chapter_id, content, note_type, is_public, likes)
        VALUES (CAST(:nid AS uuid), CAST(:uid AS uuid), :tid, :cid, :content, :nt, :pub, 0)
        ON CONFLICT (tutorial_id, user_id, chapter_id) DO UPDATE SET
          content=EXCLUDED.content, note_type=EXCLUDED.note_type, is_public=EXCLUDED.is_public
    """), {"nid": nid, "uid": current_user["user_id"], "tid": req.tutorial_id,
           "cid": req.chapter_id, "content": req.content.strip(),
           "nt": req.note_type, "pub": req.is_public})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"annotation_id": nid}}


@eight_dim_router.post("/tutorials/social-notes/{note_id}/like")
async def like_note(
    note_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        UPDATE tutorial_annotations SET likes=likes+1
        WHERE annotation_id=CAST(:nid AS uuid) AND user_id!=CAST(:uid AS uuid)
    """), {"nid": note_id, "uid": current_user["user_id"]})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}


# ── D8 成就 + 雷达图 ──────────────────────────────────────────────────────

@eight_dim_router.get("/learners/me/achievements")
async def get_achievements(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT achievement_type, achievement_name, ref_id, payload, earned_at
        FROM learner_achievements
        WHERE user_id=CAST(:uid AS uuid) ORDER BY earned_at DESC
    """), {"uid": current_user["user_id"]})).fetchall()
    return {"code": 200, "msg": "success", "data": {"achievements": [
        {"type": r.achievement_type, "name": r.achievement_name,
         "ref_id": r.ref_id, "payload": r.payload,
         "earned_at": r.earned_at.isoformat() if r.earned_at else ""}
        for r in rows
    ]}}


@eight_dim_router.get("/learners/me/mastery-radar")
async def get_mastery_radar(
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT ss.title AS stage_title, ss.stage_order,
               ROUND(AVG(COALESCE(lks.mastery_score,0))::numeric,3) AS avg_mastery,
               COUNT(DISTINCT sc.chapter_id) AS chapter_count,
               COUNT(DISTINCT CASE WHEN cp.status='read' THEN cp.chapter_id END) AS read_count
        FROM skill_blueprints sb
        JOIN skill_stages ss ON ss.blueprint_id=sb.blueprint_id
        JOIN skill_chapters sc ON sc.stage_id=ss.stage_id
        LEFT JOIN chapter_entity_links cel ON cel.chapter_id=sc.chapter_id
        LEFT JOIN learner_knowledge_states lks
               ON lks.entity_id=cel.entity_id AND lks.user_id=CAST(:uid AS uuid)
        LEFT JOIN chapter_progress cp
               ON cp.chapter_id=sc.chapter_id::text AND cp.user_id=CAST(:uid AS uuid)
        WHERE sb.topic_key=:tk AND sb.status='published'
        GROUP BY ss.stage_id, ss.title, ss.stage_order
        ORDER BY ss.stage_order
    """), {"uid": current_user["user_id"], "tk": topic_key})).fetchall()
    stages = [{"label": r.stage_title, "avg_mastery": float(r.avg_mastery),
               "chapter_count": r.chapter_count, "read_count": r.read_count}
              for r in rows]
    overall = round(sum(s["avg_mastery"] for s in stages) / len(stages), 3) if stages else 0.0
    return {"code": 200, "msg": "success", "data": {"stages": stages, "overall": overall}}



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
          AND sc_tgt.chapter_id != CAST(:chapter_id AS uuid)
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

# ── AI 合并笔记 ───────────────────────────────────────────────────────────

class NoteMergeRequest(BaseModel):
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

    await db.commit()  # 提交事务，释放连接后再调用 LLM

    fragments = "\n\n---\n\n".join(
        f"【{r.title or '无标题'}】\n{r.content}" for r in rows
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

    result = await gw.generate(prompt, model_route='knowledge_extraction')
    lines = result.strip().split("\n", 1)
    title = lines[0].lstrip("#").strip() if lines else "AI 整理笔记"
    content = lines[1].strip() if len(lines) > 1 else result.strip()

    return {"code": 200, "msg": "success", "data": {
        "title":   title,
        "content": content,
    }}

# ── 笔记本 CRUD ───────────────────────────────────────────────────────────

class NotebookCreateRequest(BaseModel):
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
    title = req.title.strip() or req.content[:30].replace("\n", " ")
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


# ── D2/D7 主观题 AI 批改 ──────────────────────────────────────────────────

_RUBRIC_PROMPT = (
    "评估学员回答。\n"
    "评分标准：{rubric}\n"
    "学员回答：{answer}\n"
    '输出JSON：{{"score":0.8,"is_correct":true,'
    '"feedback":"评价","key_points_hit":[],"key_points_missed":[]}}\n'
    "score>=0.6则is_correct为true。"
)


class RubricCheckRequest(BaseModel):
    question_id: str
    ai_rubric: str
    answer: str


@eight_dim_router.post("/learners/me/rubric-check")
async def rubric_check(
    req: RubricCheckRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    llm = get_llm_gateway()
    result = {"score": 0.5, "is_correct": False, "feedback": "已记录",
              "key_points_hit": [], "key_points_missed": []}
    try:
        raw = await llm.generate(
            _RUBRIC_PROMPT.format(rubric=req.ai_rubric, answer=req.answer),
            model_route="simple",
        )
        clean = raw.replace("```json", "").replace("```", "").strip()
        m = _re.search(r"\{.*\}", clean, _re.DOTALL)
        if m:
            result = json.loads(m.group())
    except Exception as e:
        logger.warning("rubric check failed", error=str(e))
    return {"code": 200, "msg": "success", "data": result}
