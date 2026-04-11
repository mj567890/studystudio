#!/usr/bin/env python3
"""
apply_8dim_backend.py
写入 eight_dim_endpoints.py 并确认 main.py 路由注册。

cd ~/studystudio && python3 apply_8dim_backend.py
完成后：docker compose build api && docker compose up -d api
"""
import re, shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent

def ok(m):   print(f"  \033[32m✓\033[0m  {m}")
def warn(m): print(f"  \033[33m⚠\033[0m  {m}")

def bak(p):
    b = p.with_suffix(p.suffix + f".bak.8dim.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(p, b)

# ════════════════════════════════════════════════════════════════
# 1. 写入 eight_dim_endpoints.py
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 写入 eight_dim_endpoints.py\033[0m")

dest = ROOT / "apps/api/modules/learner/eight_dim_endpoints.py"

# 用列表拼接避免三引号内转义问题
lines = [
    '"""',
    'apps/api/modules/learner/eight_dim_endpoints.py',
    '八维度学习增强系统 — 新增 API 端点',
    '"""',
    'from __future__ import annotations',
    'import json, uuid, re as _re',
    'import structlog',
    'from fastapi import APIRouter, Depends, HTTPException',
    'from pydantic import BaseModel',
    'from sqlalchemy import text',
    'from sqlalchemy.ext.asyncio import AsyncSession',
    'from apps.api.core.db import get_db',
    'from apps.api.core.llm_gateway import get_llm_gateway',
    'from apps.api.modules.auth.router import get_current_user',
    '',
    'logger = structlog.get_logger(__name__)',
    'eight_dim_router = APIRouter(tags=["eight-dimensions"])',
    '',
    '',
    '# ── D6 学习节奏偏好 ───────────────────────────────────────────────────────',
    '',
    '@eight_dim_router.get("/learners/me/learning-mode")',
    'async def get_learning_mode(',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    row = (await db.execute(',
    '        text("SELECT read_mode FROM learner_learning_mode WHERE user_id=CAST(:uid AS uuid)"),',
    '        {"uid": current_user["user_id"]},',
    '    )).fetchone()',
    '    return {"code": 200, "msg": "success", "data": {"read_mode": row.read_mode if row else "normal"}}',
    '',
    '',
    'class LearningModeRequest(BaseModel):',
    '    read_mode: str',
    '',
    '',
    '@eight_dim_router.post("/learners/me/learning-mode")',
    'async def set_learning_mode(',
    '    req: LearningModeRequest,',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    if req.read_mode not in ("skim", "normal", "deep"):',
    '        raise HTTPException(400, detail={"code": "DIM_001", "msg": "read_mode须为skim/normal/deep"})',
    '    await db.execute(text("""',
    '        INSERT INTO learner_learning_mode (user_id, read_mode, updated_at)',
    '        VALUES (CAST(:uid AS uuid), :mode, now())',
    '        ON CONFLICT (user_id) DO UPDATE SET read_mode=:mode, updated_at=now()',
    '    """), {"uid": current_user["user_id"], "mode": req.read_mode})',
    '    await db.commit()',
    '    return {"code": 200, "msg": "success", "data": {"read_mode": req.read_mode}}',
    '',
    '',
    '# ── D7 章末反思 ───────────────────────────────────────────────────────────',
    '',
    '_REFLECT_PROMPT = (',
    '    "你是教学反思评估专家。\\n"',
    '    "知识点：{entities}\\n"',
    '    "章节要点：{summary}\\n"',
    '    "学员解释：{answer}\\n\\n"',
    '    "输出JSON（不含markdown）：\\n"',
    '    \'{{\"score\":0.8,\"strengths\":\"理解正确处\",\'',
    '    \'\"gaps\":\"遗漏偏差\",\"suggestion\":\"改进建议\",\"corrected_example\":\"修正写法\"}}\\n\'',
    '    "score范围0-1。"',
    ')',
    '',
    '',
    'class ReflectRequest(BaseModel):',
    '    chapter_id: str',
    '    own_example: str',
    '    misconception: str = ""',
    '',
    '',
    '@eight_dim_router.post("/learners/me/reflect")',
    'async def submit_reflection(',
    '    req: ReflectRequest,',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    uid = current_user["user_id"]',
    '    ents = (await db.execute(text("""',
    '        SELECT ke.canonical_name',
    '        FROM chapter_entity_links cel',
    '        JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id',
    '        WHERE cel.chapter_id = :cid LIMIT 8',
    '    """), {"cid": req.chapter_id})).fetchall()',
    '    entities_text = ", ".join(r.canonical_name for r in ents)',
    '    ch = (await db.execute(',
    '        text("SELECT title, content_text FROM skill_chapters WHERE chapter_id::text=:cid LIMIT 1"),',
    '        {"cid": req.chapter_id},',
    '    )).fetchone()',
    '    summary = ""',
    '    if ch:',
    '        try:',
    '            p = json.loads(ch.content_text or "")',
    '            s = p.get("skim_summary", "")',
    '            summary = " / ".join(s) if isinstance(s, list) else str(s)',
    '        except Exception:',
    '            summary = (ch.content_text or "")[:150]',
    '    llm = get_llm_gateway()',
    '    fb = {"score": 0.5, "strengths": "已记录", "gaps": "", "suggestion": "", "corrected_example": ""}',
    '    score = 0.5',
    '    try:',
    '        raw = await llm.generate(',
    '            _REFLECT_PROMPT.format(',
    '                entities=entities_text or "（暂无）",',
    '                summary=summary or (ch.title if ch else req.chapter_id),',
    '                answer=req.own_example,',
    '            ),',
    '            model_route="simple",',
    '        )',
    '        clean = raw.replace("```json", "").replace("```", "").strip()',
    '        m = _re.search(r"\\{.*\\}", clean, _re.DOTALL)',
    '        if m:',
    '            fb = json.loads(m.group())',
    '            score = float(fb.get("score", 0.5))',
    '    except Exception as e:',
    '        logger.warning("reflect grading failed", error=str(e))',
    '    await db.execute(text("""',
    '        INSERT INTO chapter_reflections',
    '          (user_id, chapter_id, own_example, misconception, ai_feedback, ai_score, updated_at)',
    '        VALUES (CAST(:uid AS uuid), :cid, :ex, :mis, CAST(:fb AS jsonb), :score, now())',
    '        ON CONFLICT (user_id, chapter_id) DO UPDATE SET',
    '          own_example=EXCLUDED.own_example, misconception=EXCLUDED.misconception,',
    '          ai_feedback=EXCLUDED.ai_feedback, ai_score=EXCLUDED.ai_score, updated_at=now()',
    '    """), {"uid": uid, "cid": req.chapter_id, "ex": req.own_example,',
    '           "mis": req.misconception, "fb": json.dumps(fb, ensure_ascii=False), "score": score})',
    '    await db.commit()',
    '    return {"code": 200, "msg": "success", "data": {"ai_feedback": fb, "ai_score": score}}',
    '',
    '',
    '@eight_dim_router.get("/learners/me/reflect/{chapter_id}")',
    'async def get_reflection(',
    '    chapter_id: str,',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    row = (await db.execute(text("""',
    '        SELECT own_example, misconception, ai_feedback, ai_score, updated_at',
    '        FROM chapter_reflections',
    '        WHERE user_id=CAST(:uid AS uuid) AND chapter_id=:cid',
    '    """), {"uid": current_user["user_id"], "cid": chapter_id})).fetchone()',
    '    if not row:',
    '        return {"code": 200, "msg": "success", "data": None}',
    '    return {"code": 200, "msg": "success", "data": {',
    '        "own_example":   row.own_example,',
    '        "misconception": row.misconception,',
    '        "ai_feedback":   row.ai_feedback,',
    '        "ai_score":      float(row.ai_score) if row.ai_score else None,',
    '        "updated_at":    row.updated_at.isoformat() if row.updated_at else None,',
    '    }}',
    '',
    '',
    '# ── D4 社区笔记 ───────────────────────────────────────────────────────────',
    '',
    'class SocialNoteRequest(BaseModel):',
    '    tutorial_id: str',
    '    chapter_id: str',
    '    note_type: str = "tip"',
    '    content: str',
    '    is_public: bool = True',
    '',
    '',
    '@eight_dim_router.get("/tutorials/social-notes/{chapter_id}")',
    'async def get_social_notes(',
    '    chapter_id: str,',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    result = await db.execute(text("""',
    "        SELECT ta.annotation_id::text AS aid, ta.note_type, ta.content,",
    "               ta.likes, ta.user_id::text AS uid, u.nickname, ta.created_at",
    "        FROM tutorial_annotations ta",
    "        JOIN users u ON u.user_id = ta.user_id",
    "        WHERE ta.chapter_id=:cid AND ta.is_public=true",
    "          AND ta.note_type IN ('stuck','tip','ai_summary')",
    "        ORDER BY ta.likes DESC, ta.created_at DESC LIMIT 20",
    '    """), {"cid": chapter_id})',
    '    me = current_user["user_id"]',
    '    notes = [{"id": r.aid, "note_type": r.note_type, "content": r.content,',
    '               "likes": r.likes, "is_mine": r.uid == me,',
    '               "nickname": r.nickname or "匿名学员",',
    '               "created_at": r.created_at.isoformat() if r.created_at else ""}',
    '             for r in result.fetchall()]',
    '    return {"code": 200, "msg": "success", "data": {"notes": notes}}',
    '',
    '',
    '@eight_dim_router.post("/tutorials/social-notes")',
    'async def post_social_note(',
    '    req: SocialNoteRequest,',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    if req.note_type not in ("stuck", "tip"):',
    '        raise HTTPException(400, detail={"code": "DIM_002", "msg": "note_type须为stuck/tip"})',
    '    if len(req.content.strip()) < 5:',
    '        raise HTTPException(400, detail={"code": "DIM_003", "msg": "内容太短"})',
    '    nid = str(uuid.uuid4())',
    '    await db.execute(text("""',
    '        INSERT INTO tutorial_annotations',
    '          (annotation_id, user_id, tutorial_id, chapter_id, content, note_type, is_public, likes)',
    '        VALUES (CAST(:nid AS uuid), CAST(:uid AS uuid), :tid, :cid, :content, :nt, :pub, 0)',
    '        ON CONFLICT (tutorial_id, user_id, chapter_id) DO UPDATE SET',
    '          content=EXCLUDED.content, note_type=EXCLUDED.note_type, is_public=EXCLUDED.is_public',
    '    """), {"nid": nid, "uid": current_user["user_id"], "tid": req.tutorial_id,',
    '           "cid": req.chapter_id, "content": req.content.strip(),',
    '           "nt": req.note_type, "pub": req.is_public})',
    '    await db.commit()',
    '    return {"code": 200, "msg": "success", "data": {"annotation_id": nid}}',
    '',
    '',
    '@eight_dim_router.post("/tutorials/social-notes/{note_id}/like")',
    'async def like_note(',
    '    note_id: str,',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    await db.execute(text("""',
    '        UPDATE tutorial_annotations SET likes=likes+1',
    '        WHERE annotation_id=CAST(:nid AS uuid) AND user_id!=CAST(:uid AS uuid)',
    '    """), {"nid": note_id, "uid": current_user["user_id"]})',
    '    await db.commit()',
    '    return {"code": 200, "msg": "success", "data": {}}',
    '',
    '',
    '# ── D8 成就 + 雷达图 ──────────────────────────────────────────────────────',
    '',
    '@eight_dim_router.get("/learners/me/achievements")',
    'async def get_achievements(',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    rows = (await db.execute(text("""',
    '        SELECT achievement_type, achievement_name, ref_id, payload, earned_at',
    '        FROM learner_achievements',
    '        WHERE user_id=CAST(:uid AS uuid) ORDER BY earned_at DESC',
    '    """), {"uid": current_user["user_id"]})).fetchall()',
    '    return {"code": 200, "msg": "success", "data": {"achievements": [',
    '        {"type": r.achievement_type, "name": r.achievement_name,',
    '         "ref_id": r.ref_id, "payload": r.payload,',
    '         "earned_at": r.earned_at.isoformat() if r.earned_at else ""}',
    '        for r in rows',
    '    ]}}',
    '',
    '',
    '@eight_dim_router.get("/learners/me/mastery-radar")',
    'async def get_mastery_radar(',
    '    topic_key: str,',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    rows = (await db.execute(text("""',
    "        SELECT ss.title AS stage_title, ss.stage_order,",
    "               ROUND(AVG(COALESCE(lks.mastery_score,0))::numeric,3) AS avg_mastery,",
    "               COUNT(DISTINCT sc.chapter_id) AS chapter_count,",
    "               COUNT(DISTINCT CASE WHEN cp.status='read' THEN cp.chapter_id END) AS read_count",
    "        FROM skill_blueprints sb",
    "        JOIN skill_stages ss ON ss.blueprint_id=sb.blueprint_id",
    "        JOIN skill_chapters sc ON sc.stage_id=ss.stage_id",
    "        LEFT JOIN chapter_entity_links cel ON cel.chapter_id=sc.chapter_id::text",
    "        LEFT JOIN learner_knowledge_states lks",
    "               ON lks.entity_id=cel.entity_id AND lks.user_id=CAST(:uid AS uuid)",
    "        LEFT JOIN chapter_progress cp",
    "               ON cp.chapter_id=sc.chapter_id::text AND cp.user_id=CAST(:uid AS uuid)",
    "        WHERE sb.topic_key=:tk AND sb.status='published'",
    "        GROUP BY ss.stage_id, ss.title, ss.stage_order",
    "        ORDER BY ss.stage_order",
    '    """), {"uid": current_user["user_id"], "tk": topic_key})).fetchall()',
    '    stages = [{"label": r.stage_title, "avg_mastery": float(r.avg_mastery),',
    '               "chapter_count": r.chapter_count, "read_count": r.read_count}',
    '              for r in rows]',
    '    overall = round(sum(s["avg_mastery"] for s in stages) / len(stages), 3) if stages else 0.0',
    '    return {"code": 200, "msg": "success", "data": {"stages": stages, "overall": overall}}',
    '',
    '',
    '# ── D2/D7 主观题 AI 批改 ──────────────────────────────────────────────────',
    '',
    '_RUBRIC_PROMPT = (',
    '    "评估学员回答。\\n"',
    '    "评分标准：{rubric}\\n"',
    '    "学员回答：{answer}\\n"',
    '    \'输出JSON：{{\"score\":0.8,\"is_correct\":true,\'',
    '    \'\"feedback\":\"评价\",\"key_points_hit\":[],\"key_points_missed\":[]}}\\n\'',
    '    "score>=0.6则is_correct为true。"',
    ')',
    '',
    '',
    'class RubricCheckRequest(BaseModel):',
    '    question_id: str',
    '    ai_rubric: str',
    '    answer: str',
    '',
    '',
    '@eight_dim_router.post("/learners/me/rubric-check")',
    'async def rubric_check(',
    '    req: RubricCheckRequest,',
    '    current_user: dict = Depends(get_current_user),',
    '    db: AsyncSession = Depends(get_db),',
    '):',
    '    llm = get_llm_gateway()',
    '    result = {"score": 0.5, "is_correct": False, "feedback": "已记录",',
    '              "key_points_hit": [], "key_points_missed": []}',
    '    try:',
    '        raw = await llm.generate(',
    '            _RUBRIC_PROMPT.format(rubric=req.ai_rubric, answer=req.answer),',
    '            model_route="simple",',
    '        )',
    '        clean = raw.replace("```json", "").replace("```", "").strip()',
    '        m = _re.search(r"\\{.*\\}", clean, _re.DOTALL)',
    '        if m:',
    '            result = json.loads(m.group())',
    '    except Exception as e:',
    '        logger.warning("rubric check failed", error=str(e))',
    '    return {"code": 200, "msg": "success", "data": result}',
]

dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
ok(f"eight_dim_endpoints.py 写入完成 ({len(lines)} 行)")

# 语法检查
import py_compile, tempfile, os
try:
    py_compile.compile(str(dest), doraise=True)
    ok("语法检查通过")
except py_compile.PyCompileError as e:
    warn(f"语法错误：{e}")

# ════════════════════════════════════════════════════════════════
# 2. 确认 main.py 路由注册
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 确认 main.py 路由注册\033[0m")

MAIN = ROOT / "apps/api/main.py"
src  = MAIN.read_text(encoding="utf-8")

IMPORT_LINE  = "from apps.api.modules.learner.eight_dim_endpoints import eight_dim_router"
INCLUDE_LINE = "    app.include_router(eight_dim_router)"

need_write = False

if IMPORT_LINE not in src:
    old = "from apps.api.modules.skill_blueprint.router import router as blueprint_router"
    src = src.replace(old, old + "\n" + IMPORT_LINE)
    need_write = True
    ok("import 行已添加")
else:
    ok("import 行已存在")

if INCLUDE_LINE not in src:
    old = "    app.include_router(blueprint_router)"
    src = src.replace(old, old + "\n" + INCLUDE_LINE)
    need_write = True
    ok("include_router 行已添加")
else:
    ok("include_router 行已存在")

if need_write:
    bak(MAIN)
    MAIN.write_text(src, encoding="utf-8")
    ok("main.py 已更新")
else:
    ok("main.py 无需修改")

print("""
\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m
\033[32m  完成 ✅  执行：\033[0m
\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m

  docker compose build api && docker compose up -d api
""")
