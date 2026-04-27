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
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.db import get_db
from apps.api.core.llm_gateway import get_llm_gateway
from apps.api.modules.auth.router import get_current_user

logger = structlog.get_logger(__name__)
eight_dim_router = APIRouter(prefix="/api", tags=["eight-dimensions"])


def _missing_table(e: Exception) -> bool:
    """检测是否为表/列不存在的数据库错误"""
    msg = str(e).lower()
    return "does not exist" in msg or "relation" in msg


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
    '{"score":0.8,"strengths":"理解正确处",'
    '"gaps":"遗漏偏差","suggestion":"改进建议","corrected_example":"修正写法"}\n'
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
    entities_text = ""
    summary = ""
    try:
        ents = (await db.execute(text("""
            SELECT ke.canonical_name
            FROM chapter_entity_links cel
            JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
            WHERE cel.chapter_id = :cid LIMIT 8
        """), {"cid": req.chapter_id})).fetchall()
        entities_text = ", ".join(r.canonical_name for r in ents)
    except ProgrammingError:
        pass
    try:
        ch = (await db.execute(
            text("SELECT title, content_text, skim_summary FROM skill_chapters WHERE chapter_id::text=:cid LIMIT 1"),
            {"cid": req.chapter_id},
        )).fetchone()
        if ch:
            # Phase 8：优先使用结构化列 skim_summary
            if ch.skim_summary:
                s = ch.skim_summary
                try:
                    s = json.loads(s) if s.startswith("[") else s
                except Exception:
                    pass
                summary = " / ".join(s) if isinstance(s, list) else str(s)
            else:
                try:
                    p = json.loads(ch.content_text or "")
                    s = p.get("skim_summary", "")
                    summary = " / ".join(s) if isinstance(s, list) else str(s)
                except Exception:
                    summary = (ch.content_text or "")[:150]
    except ProgrammingError:
        pass
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
        logger.warning("rubric raw", raw=raw[:300])  # rubric_debug_v1
        # rubric_unescape_v1: LLM 把 {{}} 原样输出，需先还原再解析
        clean = raw.replace("```json", "").replace("```", "")\
            .replace("{{", "{").replace("}}", "}").strip()
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
        SELECT ta.annotation_id::text AS aid, ta.gap_types AS content,
               ta.is_weak_point, ta.user_id::text AS uid, u.nickname, ta.created_at
        FROM tutorial_annotations ta
        JOIN users u ON u.user_id = ta.user_id
        WHERE ta.chapter_id=:cid
        ORDER BY ta.priority_boost DESC, ta.created_at DESC LIMIT 20
    """), {"cid": chapter_id})
    me = current_user["user_id"]
    notes = [{"id": r.aid, "note_type": "gap", "content": r.content,
               "likes": 0, "is_mine": r.uid == me,
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
    import json as _json
    nid = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO tutorial_annotations
          (annotation_id, user_id, tutorial_id, chapter_id, gap_types, priority_boost)
        VALUES (CAST(:nid AS uuid), CAST(:uid AS uuid), :tid, :cid,
                CAST(:gaps AS jsonb), 1.0)
        ON CONFLICT (tutorial_id, user_id, chapter_id) DO UPDATE SET
          gap_types=EXCLUDED.gap_types, priority_boost=tutorial_annotations.priority_boost + 0.5
    """), {"nid": nid, "uid": current_user["user_id"], "tid": req.tutorial_id,
           "cid": req.chapter_id,
           "gaps": _json.dumps({"type": req.note_type, "content": req.content.strip()})})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"annotation_id": nid}}


@eight_dim_router.post("/tutorials/social-notes/{note_id}/like")
async def like_note(
    note_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        UPDATE tutorial_annotations SET priority_boost = priority_boost + 1
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
    space_id: str | None = None,
):
    _radar_sql_base = """
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
    """
    if space_id:
        _radar_sql = _radar_sql_base + " AND sb.space_id=CAST(:sid AS uuid) GROUP BY ss.stage_id, ss.title, ss.stage_order ORDER BY ss.stage_order"
        _radar_params = {"uid": current_user["user_id"], "tk": topic_key, "sid": space_id}
    else:
        _radar_sql = _radar_sql_base + " GROUP BY ss.stage_id, ss.title, ss.stage_order ORDER BY ss.stage_order"
        _radar_params = {"uid": current_user["user_id"], "tk": topic_key}
    try:
        rows = (await db.execute(text(_radar_sql), _radar_params)).fetchall()
        stages = [{"label": r.stage_title, "avg_mastery": float(r.avg_mastery),
                   "chapter_count": r.chapter_count, "read_count": r.read_count}
                  for r in rows]
    except ProgrammingError:
        stages = []
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
    try:
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
    except ProgrammingError:
        items = []
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
    try:
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
    except ProgrammingError:
        recs = []
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
    try:
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
    except ProgrammingError:
        patterns = []
    return {"code": 200, "msg": "success", "data": {"patterns": patterns}}








# ── 学习墙 ───────────────────────────────────────────────────────────────

class WallPostRequest(BaseModel):
    chapter_id: str
    topic_key:  str = ""
    space_id:   str = ""
    post_type:  str = "stuck"   # stuck | tip | discuss
    content:    str

class WallReplyRequest(BaseModel):
    content: str


@eight_dim_router.get("/wall/posts")
async def list_wall_posts(
    chapter_id: str = "",
    topic_key:  str = "",
    space_id:   str = "",
    post_type:  str = "",
    status:     str = "",
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conditions = ["1=1"]
    params: dict = {}
    if chapter_id:
        conditions.append("p.chapter_id = :chapter_id")
        params["chapter_id"] = chapter_id
    if topic_key:
        conditions.append("p.topic_key = :topic_key")
        params["topic_key"] = topic_key
    if space_id:
        conditions.append("p.space_id = CAST(:space_id AS uuid)")
        params["space_id"] = space_id
    if post_type:
        conditions.append("p.post_type = :post_type")
        params["post_type"] = post_type
    if status:
        conditions.append("p.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    rows = (await db.execute(text(f"""
        SELECT p.post_id::text, p.user_id::text, p.chapter_id, p.topic_key,
               p.post_type, p.content, p.status, p.is_featured, p.likes,
               p.space_id::text AS space_id, p.created_at, p.updated_at,
               u.nickname, u.avatar_url,
               COUNT(r.reply_id) AS reply_count
        FROM wall_posts p
        JOIN users u ON u.user_id = p.user_id
        LEFT JOIN wall_replies r ON r.post_id = p.post_id
        WHERE {where}
        GROUP BY p.post_id, u.nickname, u.avatar_url
        ORDER BY p.is_featured DESC, p.created_at DESC
        LIMIT 50
    """), params)).fetchall()

    post_ids = [r.post_id for r in rows]

    # 批量获取每个帖子的第一条 AI 回复
    ai_replies = {}
    if post_ids:
        placeholders = ", ".join([f"CAST(:pid{i} AS uuid)" for i in range(len(post_ids))])
        ai_params = {f"pid{i}": pid for i, pid in enumerate(post_ids)}
        ai_rows = (await db.execute(text(f"""
            SELECT DISTINCT ON (post_id) post_id::text, content
            FROM wall_replies
            WHERE post_id IN ({placeholders}) AND is_ai = true
            ORDER BY post_id, created_at
        """), ai_params)).fetchall()
        ai_replies = {r.post_id: r.content for r in ai_rows}

    posts = [
        {
            "post_id":     r.post_id,
            "user_id":     r.user_id,
            "nickname":    r.nickname or "匿名",
            "avatar_url":  r.avatar_url,
            "chapter_id":  r.chapter_id,
            "topic_key":   r.topic_key,
            "post_type":   r.post_type,
            "content":     r.content,
            "status":      r.status,
            "is_featured": r.is_featured,
            "likes":       r.likes,
            "reply_count": r.reply_count,
            "created_at":  r.created_at.isoformat(),
            "space_id":    r.space_id,
            "is_mine":     r.user_id == str(current_user["user_id"]),
            "ai_reply":    ai_replies.get(r.post_id),
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"posts": posts}}


@eight_dim_router.post("/wall/posts")
async def create_wall_post(
    req: WallPostRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.content.strip():
        raise HTTPException(400, detail={"msg": "内容不能为空"})
    uid = current_user["user_id"]
    pid = str(uuid.uuid4())
    sid = req.space_id if req.space_id else None
    await db.execute(text("""
        INSERT INTO wall_posts (post_id, user_id, chapter_id, topic_key, space_id, post_type, content)
        VALUES (CAST(:pid AS uuid), CAST(:uid AS uuid), :cid, :tk,
                CAST(:sid AS uuid), :pt, :content)
    """), {"pid": pid, "uid": uid, "cid": req.chapter_id,
            "tk": req.topic_key, "sid": sid, "pt": req.post_type, "content": req.content})
    await db.commit()

    # 求助型帖子 AI 自动初答（后台异步，不阻塞发帖响应）
    if req.post_type == "stuck":
        import asyncio
        async def _ai_reply_bg(post_id: str, topic_key: str, content: str, user_id: str):
            try:
                from apps.api.core.llm_gateway import LLMGateway
                from apps.api.core.db import async_session_factory
                gw = LLMGateway()
                prompt = f"""一位学员在学习「{topic_key}」时遇到了困难，发帖内容如下：

{content}

请给出一个简洁、有针对性的引导性回答（不要直接给出完整答案，而是帮助学员自己思考），100字以内。"""
                ai_content = await gw.generate(prompt, model_route="knowledge_extraction")
                rid = str(uuid.uuid4())
                async with async_session_factory() as bg_db:
                    await bg_db.execute(text("""
                        INSERT INTO wall_replies (reply_id, post_id, user_id, content, is_ai)
                        VALUES (CAST(:rid AS uuid), CAST(:pid AS uuid),
                                CAST(:uid AS uuid), :content, true)
                    """), {"rid": rid, "pid": post_id, "uid": user_id, "content": ai_content})
                    await bg_db.commit()
            except Exception:
                pass
        asyncio.create_task(_ai_reply_bg(pid, req.topic_key, req.content, str(uid)))

    return {"code": 200, "msg": "success", "data": {
        "post_id": pid, "ai_reply": None
    }}


@eight_dim_router.get("/wall/posts/joined")
async def list_joined_posts(
    limit:  int = 30,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回当前用户加入的所有课程的最新帖子（全局聚合）。"""
    uid = current_user["user_id"]
    rows = (await db.execute(text("""
        SELECT p.post_id::text, p.user_id::text, p.chapter_id,
               p.space_id::text AS space_id, p.post_type, p.content,
               p.status, p.is_featured, p.likes, p.created_at,
               u.nickname, u.avatar_url,
               COUNT(r.reply_id) AS reply_count,
               ks.name AS space_name
        FROM wall_posts p
        JOIN users u ON u.user_id = p.user_id
        LEFT JOIN wall_replies r ON r.post_id = p.post_id
        JOIN space_members sm ON sm.space_id = p.space_id
                              AND sm.user_id = CAST(:uid AS uuid)
        JOIN knowledge_spaces ks ON ks.space_id = p.space_id
        WHERE p.space_id IS NOT NULL
        GROUP BY p.post_id, u.nickname, u.avatar_url, ks.name
        ORDER BY p.created_at DESC
        LIMIT :limit OFFSET :offset
    """), {"uid": uid, "limit": limit, "offset": offset})).fetchall()

    posts = [
        {
            "post_id":     r.post_id,
            "user_id":     r.user_id,
            "nickname":    r.nickname or "匿名",
            "avatar_url":  r.avatar_url,
            "space_id":    r.space_id,
            "space_name":  r.space_name,
            "chapter_id":  r.chapter_id,
            "post_type":   r.post_type,
            "content":     r.content,
            "status":      r.status,
            "is_featured": r.is_featured,
            "likes":       r.likes,
            "reply_count": r.reply_count,
            "created_at":  r.created_at.isoformat(),
            "is_mine":     r.user_id == str(uid),
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"posts": posts, "total": len(posts)}}

@eight_dim_router.get("/wall/posts/{post_id}/replies")
async def list_replies(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT r.reply_id::text, r.user_id::text, r.content, r.is_ai,
               r.likes, r.created_at, u.nickname, u.avatar_url
        FROM wall_replies r
        JOIN users u ON u.user_id = r.user_id
        WHERE r.post_id = CAST(:pid AS uuid)
        ORDER BY r.created_at
    """), {"pid": post_id})).fetchall()

    replies = [
        {
            "reply_id":   r.reply_id,
            "user_id":    r.user_id,
            "nickname":   r.nickname or "匿名",
            "avatar_url": r.avatar_url,
            "content":    r.content,
            "is_ai":      r.is_ai,
            "likes":      r.likes,
            "created_at": r.created_at.isoformat(),
            "is_mine":    r.user_id == str(current_user["user_id"]),
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"replies": replies}}


@eight_dim_router.post("/wall/posts/{post_id}/replies")
async def create_reply(
    post_id: str,
    req: WallReplyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.content.strip():
        raise HTTPException(400, detail={"msg": "回复内容不能为空"})
    rid = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO wall_replies (reply_id, post_id, user_id, content)
        VALUES (CAST(:rid AS uuid), CAST(:pid AS uuid), CAST(:uid AS uuid), :content)
    """), {"rid": rid, "pid": post_id, "uid": current_user["user_id"], "content": req.content})
    await db.execute(text("""
        UPDATE wall_posts SET updated_at = NOW()
        WHERE post_id = CAST(:pid AS uuid)
    """), {"pid": post_id})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"reply_id": rid}}


@eight_dim_router.post("/wall/posts/{post_id}/resolve")
async def resolve_post(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        UPDATE wall_posts SET status = 'resolved'
        WHERE post_id = CAST(:pid AS uuid) AND user_id = CAST(:uid AS uuid)
    """), {"pid": post_id, "uid": current_user["user_id"]})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}

@eight_dim_router.post("/wall/posts/{post_id}/like")
async def like_post(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("""
        UPDATE wall_posts SET likes = likes + 1
        WHERE post_id = CAST(:pid AS uuid)
    """), {"pid": post_id})
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}

# ── 阶段能力证书 PDF ──────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse
import io
from datetime import datetime

@eight_dim_router.get("/learners/me/certificate")
async def download_certificate(
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    space_id: str | None = None,
):
    uid = current_user["user_id"]

    # 查用户信息
    user_row = (await db.execute(text("""
        SELECT nickname, email FROM users WHERE user_id = CAST(:uid AS uuid)
    """), {"uid": uid})).fetchone()
    nickname = (user_row.nickname or user_row.email.split("@")[0]) if user_row else "学员"

    # 查主题信息和完成情况（skill_blueprints/skill_chapters 表已废弃，暂时返回不支持）
    try:
        _t1_sql = "SELECT title FROM skill_blueprints WHERE topic_key = :tk"
        _t1_sql += " AND space_id=CAST(:sid AS uuid)" if space_id else ""
        _t1_sql += " LIMIT 1"
        _t1_params = {"tk": topic_key, **( {"sid": space_id} if space_id else {})}
        topic_row = (await db.execute(text(_t1_sql), _t1_params)).fetchone()
        topic_name = topic_row.title if topic_row else topic_key

        _t2_sql = "SELECT COUNT(*) FROM skill_chapters sc JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id WHERE sb.topic_key = :tk"
        _t2_sql += " AND sb.space_id=CAST(:sid AS uuid)" if space_id else ""
        _t2_params = {"tk": topic_key, **( {"sid": space_id} if space_id else {})}
        total = (await db.execute(text(_t2_sql), _t2_params)).scalar() or 0

        _t3_sql = """SELECT COUNT(DISTINCT sc.chapter_id)
            FROM skill_chapters sc
            JOIN skill_blueprints sb ON sb.blueprint_id = sc.blueprint_id
            JOIN chapter_progress cp
              ON cp.chapter_id = sc.chapter_id::text
             AND cp.user_id = CAST(:uid AS uuid)
             AND cp.status = 'read'
            WHERE sb.topic_key = :tk"""
        _t3_sql += " AND sb.space_id=CAST(:sid AS uuid)" if space_id else ""
        _t3_params = {"uid": uid, "tk": topic_key, **( {"sid": space_id} if space_id else {})}
        completed = (await db.execute(text(_t3_sql), _t3_params)).scalar() or 0
    except ProgrammingError:
        raise HTTPException(400, detail={
            "code": "CERT_002",
            "msg": "证书功能暂不可用，系统正在升级中"
        })

    if total == 0 or completed < total:
        raise HTTPException(400, detail={
            "code": "CERT_001",
            "msg": f"尚未完成全部章节（{completed}/{total}），无法颁发证书"
        })

    await db.commit()  # 数据读取完毕，提交释放连接

    # 生成证书编号
    import hashlib
    cert_no = hashlib.md5(f"{uid}{topic_key}{datetime.utcnow().date()}".encode()).hexdigest()[:12].upper()
    issue_date = datetime.utcnow().strftime("%Y年%m月%d日")

    # 生成 PDF
    pdf_buf = _build_certificate_pdf(nickname, topic_name, issue_date, cert_no)

    # 把 bytes 全部读出来，避免 StreamingResponse 惰性读取时 session 已关闭
    pdf_bytes = pdf_buf.read()
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate_{topic_key}.pdf"'}
    )


def _build_certificate_pdf(name: str, topic: str, date: str, cert_no: str) -> io.BytesIO:
    from fpdf import FPDF

    FONT_PATH = "/app/apps/api/assets/fonts/NotoSansCJK.ttf"

    class CertPDF(FPDF):
        pass

    pdf = CertPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    pdf.add_font("Noto", "", FONT_PATH)

    W, H = 297, 210  # A4 横版

    # 背景色
    pdf.set_fill_color(248, 246, 240)
    pdf.rect(0, 0, W, H, "F")

    # 外边框
    pdf.set_draw_color(201, 168, 76)
    pdf.set_line_width(1.2)
    pdf.rect(10, 10, W-20, H-20)

    # 内边框
    pdf.set_line_width(0.4)
    pdf.rect(14, 14, W-28, H-28)

    # 标题
    pdf.set_font("Noto", size=36)
    pdf.set_text_color(44, 44, 44)
    pdf.set_y(30)
    pdf.cell(0, 15, "结  业  证  书", align="C", ln=True)

    # 副标题
    pdf.set_font("Noto", size=12)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 8, "CERTIFICATE OF COMPLETION", align="C", ln=True)

    # 分隔线
    pdf.set_draw_color(201, 168, 76)
    pdf.set_line_width(0.3)
    pdf.line(50, pdf.get_y()+3, W-50, pdf.get_y()+3)
    pdf.ln(10)

    # 正文
    pdf.set_font("Noto", size=14)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 10, "兹证明", align="C", ln=True)

    # 姓名
    pdf.set_font("Noto", size=28)
    pdf.set_text_color(201, 168, 76)
    pdf.cell(0, 14, name, align="C", ln=True)

    # 姓名下划线
    y = pdf.get_y()
    pdf.set_draw_color(201, 168, 76)
    pdf.set_line_width(0.5)
    pdf.line(90, y, W-90, y)
    pdf.ln(8)

    # 完成说明
    pdf.set_font("Noto", size=14)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 10, f"已完成「{topic}」全部学习内容", align="C", ln=True)
    pdf.cell(0, 10, "具备该领域的系统知识与实践能力", align="C", ln=True)

    # 底部信息
    pdf.set_y(H - 22)
    pdf.set_font("Noto", size=10)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(60, 8, f"颁发日期：{date}", align="L")
    pdf.cell(0, 8, f"StudyStudio 自适应学习平台", align="C")
    pdf.cell(-60, 8, f"证书编号：{cert_no}", align="R")

    buf = io.BytesIO(pdf.output())
    return buf

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

    # 取出数据后不再使用 db，让 FastAPI 在请求结束时自动归还连接
    note_data = [(r.title, r.content) for r in rows]

    fragments = "\n\n---\n\n".join(
        f"【{title or '无标题'}】\n{content}" for title, content in note_data
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

    # Phase 9.2：批量加载笔记关联的知识实体
    note_entities: dict[str, list[dict]] = {}
    if notes:
        note_ids = [n["note_id"] for n in notes]
        entity_rows = (await db.execute(text("""
            SELECT nel.note_id::text, ke.entity_id::text, ke.canonical_name, ke.short_definition
            FROM note_entity_links nel
            JOIN knowledge_entities ke ON ke.entity_id = nel.entity_id
            WHERE nel.note_id = ANY(CAST(:nids AS uuid[]))
        """), {"nids": note_ids})).fetchall()
        for er in entity_rows:
            note_entities.setdefault(er.note_id, []).append({
                "entity_id":         er.entity_id,
                "canonical_name":    er.canonical_name,
                "short_definition":  (er.short_definition or "")[:120],
            })
    for n in notes:
        n["linked_entities"] = note_entities.get(n["note_id"], [])

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

    # Phase 9.2：若笔记关联了章节，自动提取章节的知识实体并建立关联
    linked_count = 0
    if req.chapter_id:
        try:
            entity_rows = (await db.execute(text("""
                SELECT cel.entity_id
                FROM chapter_entity_links cel
                WHERE cel.chapter_id = CAST(:chid AS uuid)
                LIMIT 20
            """), {"chid": req.chapter_id})).fetchall()
            for er in entity_rows:
                await db.execute(text("""
                    INSERT INTO note_entity_links (note_id, entity_id)
                    VALUES (CAST(:nid AS uuid), :eid)
                    ON CONFLICT DO NOTHING
                """), {"nid": nid, "eid": er.entity_id})
                linked_count += 1
        except Exception:
            pass  # 实体关联失败不阻断笔记创建

    await db.commit()
    return {
        "code": 200, "msg": "success",
        "data": {"note_id": nid, "title": title, "linked_entities": linked_count},
    }


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


# ── Phase 9.2 按知识点查看笔记 ──────────────────────────────────────────

@eight_dim_router.get("/learners/me/notes/by-entity/{entity_id}")
async def get_notes_by_entity(
    entity_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回某个知识实体关联的所有笔记（含实体基本信息）。"""
    uid = current_user["user_id"]
    # 获取实体基本信息
    e_row = (await db.execute(text("""
        SELECT entity_id::text, canonical_name, short_definition, domain_tag
        FROM knowledge_entities
        WHERE entity_id = CAST(:eid AS uuid)
    """), {"eid": entity_id})).fetchone()
    if not e_row:
        raise HTTPException(404, detail={"code": "NOTE_002", "msg": "知识点不存在"})

    entity_info = {
        "entity_id":        e_row.entity_id,
        "canonical_name":   e_row.canonical_name,
        "short_definition": e_row.short_definition,
        "domain_tag":       e_row.domain_tag,
    }

    rows = (await db.execute(text("""
        SELECT ln.note_id::text, ln.title, ln.content, ln.source_type,
               ln.chapter_id, ln.chapter_title, ln.topic_key,
               ln.tags, ln.created_at, ln.updated_at
        FROM learner_notes ln
        JOIN note_entity_links nel ON nel.note_id = ln.note_id
        WHERE nel.entity_id = CAST(:eid AS uuid)
          AND ln.user_id    = CAST(:uid AS uuid)
        ORDER BY ln.created_at DESC
        LIMIT 50
    """), {"eid": entity_id, "uid": uid})).fetchall()

    import json as _j_ne
    notes = [{
        "note_id":       r.note_id,
        "title":         r.title,
        "content":       r.content,
        "source_type":   r.source_type,
        "chapter_id":    r.chapter_id,
        "chapter_title": r.chapter_title,
        "topic_key":     r.topic_key,
        "tags":          r.tags if isinstance(r.tags, list) else _j_ne.loads(r.tags or "[]"),
        "created_at":    r.created_at.isoformat() if r.created_at else "",
        "updated_at":    r.updated_at.isoformat() if r.updated_at else "",
    } for r in rows]

    return {
        "code": 200, "msg": "success",
        "data": {"entity": entity_info, "notes": notes, "total": len(notes)},
    }

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
    "你是严格的评分助手。评估学员回答并输出JSON，不要输出任何其他内容。\n"
    "评分标准：{rubric}\n"
    "学员回答：{answer}\n"
    "要求：score必须是0到1之间的浮点数（如0.8），is_correct为布尔值，score>=0.6时is_correct为true。\n"
    '严格按此格式输出，不含markdown代码块：{"score":0.8,"is_correct":true,'
    '"feedback":"具体评价","key_points_hit":["要点1"],"key_points_missed":["要点2"]}}'
)  # rubric_prompt_final_v1


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
            # rubric_no_format_v1: 用拼接代替 format，避免 ai_rubric 含大括号报 KeyError
            _RUBRIC_PROMPT
            .replace("{rubric}", req.ai_rubric)
            .replace("{answer}", req.answer),
            model_route="teaching_chat_simple"
        )
        logger.warning("rubric raw", raw=raw[:300])  # rubric_debug_v1
        # rubric_unescape_v1: LLM 把 {{}} 原样输出，需先还原再解析
        clean = raw.replace("```json", "").replace("```", "")\
            .replace("{{", "{").replace("}}", "}").strip()
        m = _re.search(r"\{.*\}", clean, _re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
                logger.warning("rubric parsed", parsed=str(parsed)[:200])
                result = {
                    "score": float(str(parsed.get("score", 0.5))),
                    "is_correct": parsed.get("score", 0) >= 0.6,
                    "feedback": str(parsed.get("feedback", "")),
                    "key_points_hit": parsed.get("key_points_hit", []),
                    "key_points_missed": parsed.get("key_points_missed", []),
                }
            except Exception as pe:
                logger.warning("rubric parse error", error=str(pe), raw=clean[:200])
    except Exception as e:
        logger.warning("rubric check failed", error=str(e))
    return {"code": 200, "msg": "success", "data": result}


# ── Phase 9.3 学习进度仪表板 ──────────────────────────────────────────────

@eight_dim_router.get("/learners/me/dashboard")
async def get_learner_dashboard(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回首页仪表板聚合数据：最近学习记录、薄弱章节、继续上次学习。"""
    uid = current_user["user_id"]

    # 1. 最近学习记录（最近 5 条已完成的章节进度）
    recent_rows = (await db.execute(text("""
        SELECT cp.chapter_id::text, cp.completed_at,
               sc.title AS chapter_title, ss.title AS stage_title,
               sb.topic_key, sb.title AS blueprint_title
        FROM chapter_progress cp
        JOIN skill_chapters sc ON sc.chapter_id::text = cp.chapter_id
        JOIN skill_stages   ss ON ss.stage_id   = sc.stage_id
        JOIN skill_blueprints sb ON sb.blueprint_id = ss.blueprint_id
        WHERE cp.user_id = CAST(:uid AS uuid) AND cp.completed = true
        ORDER BY cp.completed_at DESC
        LIMIT 5
    """), {"uid": uid})).fetchall()

    recent = [{
        "chapter_id":      str(r.chapter_id),
        "chapter_title":   r.chapter_title,
        "stage_title":     r.stage_title,
        "topic_key":       r.topic_key,
        "blueprint_title": r.blueprint_title,
        "completed_at":    r.completed_at.isoformat() if r.completed_at else None,
    } for r in recent_rows]

    # 2. 薄弱章节（平均掌握度 < 0.4）
    weak_rows = (await db.execute(text("""
        SELECT sc.chapter_id::text, sc.title AS chapter_title,
               ss.title AS stage_title, sb.topic_key, sb.title AS blueprint_title,
               ROUND(AVG(lks.mastery_score)::numeric, 3) AS avg_mastery,
               COUNT(DISTINCT cel.entity_id) AS weak_entity_count
        FROM learner_knowledge_states lks
        JOIN knowledge_entities ke ON ke.entity_id = lks.entity_id
        JOIN chapter_entity_links cel ON cel.entity_id = lks.entity_id
        JOIN skill_chapters sc ON sc.chapter_id = cel.chapter_id
        JOIN skill_stages   ss ON ss.stage_id   = sc.stage_id
        JOIN skill_blueprints sb ON sb.blueprint_id = ss.blueprint_id
                                  AND sb.status = 'published'
        WHERE lks.user_id = CAST(:uid AS uuid) AND lks.mastery_score < 0.4
        GROUP BY sc.chapter_id, sc.title, ss.title, sb.topic_key, sb.title
        ORDER BY avg_mastery ASC
        LIMIT 8
    """), {"uid": uid})).fetchall()

    weak = [{
        "chapter_id":       str(r.chapter_id),
        "chapter_title":    r.chapter_title,
        "stage_title":      r.stage_title,
        "topic_key":        r.topic_key,
        "blueprint_title":  r.blueprint_title,
        "avg_mastery":      float(r.avg_mastery),
        "weak_entity_count": r.weak_entity_count,
    } for r in weak_rows]

    # 3. 各主题上次学习章节（DISTINCT ON topic_key）
    last_rows = (await db.execute(text("""
        SELECT DISTINCT ON (sb.topic_key)
               cp.chapter_id::text, sc.title AS chapter_title,
               sb.topic_key, sb.title AS blueprint_title,
               cp.completed_at
        FROM chapter_progress cp
        JOIN skill_chapters sc ON sc.chapter_id::text = cp.chapter_id
        JOIN skill_stages   ss ON ss.stage_id   = sc.stage_id
        JOIN skill_blueprints sb ON sb.blueprint_id = ss.blueprint_id
        WHERE cp.user_id = CAST(:uid AS uuid)
        ORDER BY sb.topic_key, cp.completed_at DESC
    """), {"uid": uid})).fetchall()

    last_learned = [{
        "chapter_id":      str(r.chapter_id),
        "chapter_title":   r.chapter_title,
        "topic_key":       r.topic_key,
        "blueprint_title": r.blueprint_title,
        "completed_at":    r.completed_at.isoformat() if r.completed_at else None,
    } for r in last_rows]

    # 4. 各课程进度概览（按 topic_key 聚合已读/总章节）
    course_rows = (await db.execute(text("""
        SELECT sb.topic_key,
               COUNT(DISTINCT sc.chapter_id) AS total_chapters,
               COUNT(DISTINCT cp.chapter_id) FILTER (WHERE cp.completed = true) AS read_chapters
        FROM skill_blueprints sb
        JOIN skill_stages   ss ON ss.blueprint_id = sb.blueprint_id
        JOIN skill_chapters sc ON sc.stage_id     = ss.stage_id
        LEFT JOIN chapter_progress cp
               ON cp.chapter_id = sc.chapter_id::text
              AND cp.user_id    = CAST(:uid AS uuid)
        WHERE sb.status = 'published'
        GROUP BY sb.topic_key
    """), {"uid": uid})).fetchall()

    course_progress = [{
        "topic_key":      r.topic_key,
        "total_chapters": r.total_chapters,
        "read_chapters":  r.read_chapters or 0,
    } for r in course_rows]

    return {
        "code": 200,
        "msg":  "success",
        "data": {
            "recent_activity":  recent,
            "weak_chapters":    weak,
            "last_learned":     last_learned,
            "course_progress":  course_progress,
        },
    }
# hot reload test
