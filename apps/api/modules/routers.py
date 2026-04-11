"""
apps/api/modules/learner/learner_router.py  (Block C)
apps/api/modules/tutorial/tutorial_router.py (Block D)
apps/api/modules/teaching/teaching_router.py (Block E)

合并在一个文件中，生产时应拆分到各模块目录。
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user
from apps.api.modules.learner.learner_service import (
    ColdStartService,
    GapScanService,
    RepairPathService,
)
from apps.api.modules.teaching.teaching_service import (
    DiagnosisUpdate,
    TeachingChatService,
    _run_diagnosis_update,
)
from apps.api.modules.tutorial.tutorial_service import TutorialGenerationService

# ══════════════════════════════════════════════
# Block C 路由
# ══════════════════════════════════════════════
learner_router = APIRouter(prefix="/api/learners/me", tags=["learner"])


@learner_router.get("/profile")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    result = await db.execute(
        __import__("sqlalchemy").text(
            "SELECT mastery_summary, version, updated_at "
            "FROM learner_profiles WHERE user_id = :uid"
        ),
        {"uid": current_user["user_id"]}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "LEARNER_001", "msg": "Profile not found"})
    return {
        "code": 200, "msg": "success",
        "data": {
            "user_id":         current_user["user_id"],
            "mastery_summary": row.mastery_summary,
            "version":         row.version,
            "updated_at":      row.updated_at.isoformat() if row.updated_at else None,
        }
    }


@learner_router.get("/placement-quiz")
async def get_placement_quiz(
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    svc  = ColdStartService(db)
    quiz = await svc.get_placement_quiz(topic_key)
    return {"code": 200, "msg": "success", "data": quiz}


class PlacementAnswerItem(BaseModel):
    question_id:     str
    selected_option: str
    domain:          str = ""
    difficulty:      str = "basic"
    is_correct:      bool = False
    is_fallback:     bool = False


class PlacementResultRequest(BaseModel):
    topic_key: str
    answers:   list[PlacementAnswerItem]


@learner_router.post("/placement-result")
async def submit_placement_result(
    req: PlacementResultRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    svc    = ColdStartService(db)
    result = await svc.process_placement_result(
        current_user["user_id"],
        req.topic_key,
        [a.model_dump() for a in req.answers],
    )
    return {"code": 200, "msg": "success", "data": result}


@learner_router.get("/gaps")
async def get_gaps(
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    svc    = GapScanService(db)
    report = await svc.scan(current_user["user_id"], topic_key)
    return {"code": 200, "msg": "success", "data": report}


@learner_router.get("/repair-path")
async def get_repair_path(
    topic_key: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    svc  = RepairPathService(db)
    path = await svc.compute(current_user["user_id"], topic_key)
    return {"code": 200, "msg": "success", "data": path}


# ── 章节学习进度（前端调用但原代码缺失）────────────────────────

class ChapterProgressRequest(BaseModel):
    tutorial_id: str
    chapter_id:  str
    completed:        bool
    duration_seconds: int = 0


@learner_router.post("/chapter-progress")
async def mark_chapter_progress(
    req: ChapterProgressRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """标记章节完成/未完成。"""
    from sqlalchemy import text as _text
    await db.execute(
        _text("""
            INSERT INTO chapter_progress
              (user_id, tutorial_id, chapter_id, completed, completed_at, duration_seconds)
            VALUES
              (:uid, :tid, :chid, :done, CASE WHEN :done THEN NOW() ELSE NULL END, :dur)
            ON CONFLICT (user_id, tutorial_id, chapter_id)
            DO UPDATE SET
              completed        = EXCLUDED.completed,
              completed_at     = EXCLUDED.completed_at,
              duration_seconds = GREATEST(chapter_progress.duration_seconds, EXCLUDED.duration_seconds)
        """),
        {
            "uid":  current_user["user_id"],
            "tid":  req.tutorial_id,
            "chid": req.chapter_id,
            "done": req.completed,
            "dur":  getattr(req, "duration_seconds", 0),
        }
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {"completed": req.completed}}


@learner_router.get("/chapter-progress/{tutorial_id}")
async def get_chapter_progress(
    tutorial_id:  str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """获取某教程的章节完成进度。"""
    from sqlalchemy import text as _text
    result = await db.execute(
        _text("""
            SELECT chapter_id::text, completed, completed_at
            FROM chapter_progress
            WHERE user_id = :uid AND tutorial_id = :tid
        """),
        {"uid": current_user["user_id"], "tid": tutorial_id}
    )
    progress = {
        r.chapter_id: {
            "completed":    r.completed,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in result.fetchall()
    }
    return {"code": 200, "msg": "success", "data": {"progress": progress}}


# ══════════════════════════════════════════════
# Block D 路由
# ══════════════════════════════════════════════
tutorial_router = APIRouter(prefix="/api/tutorials", tags=["tutorial"])


@tutorial_router.get("/topic/{topic_key}")
async def get_tutorial(
    topic_key:      str,
    force_refresh:  bool = Query(False),
    current_user:   dict = Depends(get_current_user),
    db: AsyncSession     = Depends(get_db),
) -> dict:
    from sqlalchemy import text as _text

    # ── 新路径：优先读取已发布蓝图 ──
    _bp = await db.execute(
        _text("SELECT blueprint_id::text FROM skill_blueprints "
              "WHERE topic_key = :tk AND status = 'published' LIMIT 1"),
        {"tk": topic_key}
    )
    _bp_row = _bp.fetchone()
    if _bp_row:
        from apps.api.modules.skill_blueprint.service import BlueprintService
        _bp_svc = BlueprintService(db)
        _blueprint = await _bp_svc.get_blueprint(topic_key)
        if _blueprint:
            return {
                "code": 200, "msg": "success",
                "data": {
                    "source":       "blueprint",
                    "blueprint_id": _blueprint.blueprint_id,
                    "topic_key":    _blueprint.topic_key,
                    "title":        _blueprint.title,
                    "skill_goal":   _blueprint.skill_goal,
                    "stages":       [s.model_dump() for s in _blueprint.stages],
                }
            }

    # ── 旧路径：无已发布蓝图时保持原有逻辑 ──
    svc = TutorialGenerationService(db)
    # 触发或复用教程生成
    tutorial_id = await svc.generate(topic_key, current_user["user_id"], force_refresh=force_refresh)

    # 查询骨架
    result = await db.execute(
        _text("""
            SELECT ts.tutorial_id, ts.topic_key, ts.chapter_tree, ts.status
            FROM tutorial_skeletons ts
            WHERE ts.tutorial_id = :tid
        """),
        {"tid": tutorial_id}
    )
    row = result.fetchone()
    if not row:
        return {
            "code": 202, "msg": "Tutorial generation in progress",
            "data": {"tutorial_id": tutorial_id, "status": "generating"}
        }

    # ── 修复：查询章节内容并合并进 chapter_tree ──────────────────
    # 原代码只返回骨架的 chapter_tree，未包含 content_text，
    # 导致前端 currentChapter.content_text 永远为 undefined，
    # 始终显示"内容生成中，请稍后刷新页面"。
    contents_result = await db.execute(
        _text("""
            SELECT chapter_id::text, content_text, status
            FROM tutorial_contents
            WHERE tutorial_id = :tid
        """),
        {"tid": tutorial_id}
    )
    # 只取 approved 状态的内容，pending_review 暂不展示
    contents: dict[str, str] = {
        r.chapter_id: r.content_text
        for r in contents_result.fetchall()
        if r.status == "approved"
    }

    # 将 content_text 合并进 chapter_tree 中对应章节
    chapter_tree = row.chapter_tree or []
    for chapter in chapter_tree:
        ch_id = chapter.get("chapter_id")
        if ch_id and ch_id in contents:
            chapter["content_text"] = contents[ch_id]

    return {
        "code": 200, "msg": "success",
        "data": {
            "tutorial_id":  row.tutorial_id,
            "topic_key":    row.topic_key,
            "chapter_tree": chapter_tree,
            "status":       row.status,
        }
    }


# ══════════════════════════════════════════════
# Block E 路由
# ══════════════════════════════════════════════
teaching_router = APIRouter(prefix="/api/teaching", tags=["teaching"])


class ChatRequest(BaseModel):
    conversation_id: str
    message:         str
    context:         dict = {}


@teaching_router.post("/chat")
async def chat(
    req:              ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict     = Depends(get_current_user),
    db: AsyncSession       = Depends(get_db),
) -> dict:
    """
    D3+R1（V2.6）：chat_and_prepare 返回三元组，
    诊断写入通过 BackgroundTasks 后台执行，使用独立 session。
    """
    svc        = TeachingChatService(db)
    topic_key  = req.context.get("topic_key", "")
    space_id   = req.context.get("space_id") or None
    domain_tag = req.context.get("domain_tag") or None
    chapter_id = req.context.get("chapter_id") or None

    response, diagnosis, profile_version = await svc.chat_and_prepare(
        conversation_id = req.conversation_id,
        user_message    = req.message,
        topic_key       = topic_key,
        user_id         = current_user["user_id"],
        space_id        = space_id,
        domain_tag      = domain_tag,
        chapter_id      = chapter_id,
    )

    # 不传 db：响应发送后 db session 已关闭，后台任务使用独立 session
    background_tasks.add_task(
        _run_diagnosis_update,
        current_user["user_id"],
        diagnosis,
        profile_version,
    )

    return {"code": 200, "msg": "success", "data": response}


@teaching_router.post("/conversations")
async def create_conversation(
    topic_key:    str,
    title:        str = "",
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """创建新的对话会话。"""
    import uuid
    from sqlalchemy import text as _text
    conv_id       = str(uuid.uuid4())
    display_title = title or topic_key or "新对话"
    await db.execute(
        _text("""
            INSERT INTO conversations (conversation_id, user_id, topic_key)
            VALUES (:cid, :uid, :tk)
        """),
        {"cid": conv_id, "uid": current_user["user_id"], "tk": display_title}
    )
    await db.commit()
    return {"code": 201, "msg": "success", "data": {
        "conversation_id": conv_id, "title": display_title
    }}


@teaching_router.get("/conversations")
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """获取当前用户的对话列表（最近 50 条）。"""
    from sqlalchemy import text as _text
    result = await db.execute(
        _text("""
            SELECT conversation_id::text, topic_key, turn_count,
                   created_at, updated_at
            FROM conversations
            WHERE user_id = CAST(:uid AS uuid)
            ORDER BY updated_at DESC
            LIMIT 50
        """),
        {"uid": current_user["user_id"]}
    )
    rows = result.fetchall()
    convs = [
        {
            "conversation_id": r.conversation_id,
            "title":      r.topic_key,
            "turn_count": r.turn_count,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"conversations": convs}}


@teaching_router.get("/conversations/{conversation_id}/turns")
async def get_conversation_turns(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """获取指定对话的历史消息。"""
    from sqlalchemy import text as _text
    # 验证归属
    conv = await db.execute(
        _text("SELECT user_id FROM conversations WHERE conversation_id = CAST(:cid AS uuid)"),
        {"cid": conversation_id}
    )
    row = conv.fetchone()
    if not row or str(row.user_id) != current_user["user_id"]:
        return {"code": 403, "msg": "forbidden", "data": {}}
    result = await db.execute(
        _text("""
            SELECT role, content, gap_type, created_at
            FROM conversation_turns
            WHERE conversation_id = CAST(:cid AS uuid)
            ORDER BY created_at ASC
        """),
        {"cid": conversation_id}
    )
    turns = [
        {
            "role":       r.role,
            "content":    r.content,
            "gap_type":   r.gap_type,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in result.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {"turns": turns}}


@teaching_router.get("/spaces")
async def list_teaching_spaces(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """返回当前用户可用的知识空间（全局 + 本人个人空间）。"""
    from sqlalchemy import text as _text
    result = await db.execute(
        _text("""
            SELECT space_id::text, space_type,
                   COALESCE(name,
                     CASE space_type WHEN 'global' THEN '公共知识库' ELSE '我的知识库' END
                   ) AS name
            FROM knowledge_spaces
            WHERE space_type = 'global'
               OR (space_type = 'personal' AND owner_id = CAST(:uid AS uuid))
            ORDER BY space_type DESC, name
        """),
        {"uid": current_user["user_id"]}
    )
    spaces = [
        {"space_id": r.space_id, "space_type": r.space_type, "name": r.name}
        for r in result.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {"spaces": spaces}}


@teaching_router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """删除指定对话及其所有消息。"""
    from sqlalchemy import text as _text
    # 验证归属
    conv = await db.execute(
        _text("SELECT user_id FROM conversations WHERE conversation_id = CAST(:cid AS uuid)"),
        {"cid": conversation_id}
    )
    row = conv.fetchone()
    if not row or str(row.user_id) != current_user["user_id"]:
        return {"code": 403, "msg": "forbidden", "data": {}}
    # 先删消息，再删对话
    await db.execute(
        _text("DELETE FROM conversation_turns WHERE conversation_id = CAST(:cid AS uuid)"),
        {"cid": conversation_id}
    )
    await db.execute(
        _text("DELETE FROM conversations WHERE conversation_id = CAST(:cid AS uuid)"),
        {"cid": conversation_id}
    )
    await db.commit()
    return {"code": 200, "msg": "success", "data": {}}


from apps.api.core.llm_gateway import get_llm_gateway

# ════════════════════════════════════════════════════════════════
# H-2：章节测验生成 + 提交
# ════════════════════════════════════════════════════════════════
QUIZ_GENERATION_PROMPT = """你是一位出题专家。根据以下知识点，生成 {count} 道测验题。

知识点列表：
{entities_json}

要求：
- 单选题占 60%，判断题占 20%，填空/简答题占 20%（按比例取整，至少各1道）
- 每道题必须明确对应一个知识点（entity_id）
- 单选题提供4个选项（A/B/C/D），标注正确答案
- 判断题答案为 true 或 false
- 填空/简答题提供参考答案

严格按以下 JSON 格式输出，不含其他内容：
[
  {{
    "question_id": "q1",
    "entity_id": "对应知识点的entity_id",
    "type": "single_choice",
    "question": "题目内容",
    "options": {{"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}},
    "answer": "A",
    "explanation": "解析"
  }},
  {{
    "question_id": "q2",
    "entity_id": "对应知识点的entity_id",
    "type": "true_false",
    "question": "判断题内容",
    "answer": true,
    "explanation": "解析"
  }},
  {{
    "question_id": "q3",
    "entity_id": "对应知识点的entity_id",
    "type": "fill_blank",
    "question": "填空/简答题内容",
    "answer": "参考答案",
    "explanation": "解析"
  }}
]"""


@learner_router.get("/chapter-quiz/{chapter_id}")
async def get_chapter_quiz(
    chapter_id:   str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """获取章节测验题目，已生成则直接返回，否则即时生成并保存。"""
    from sqlalchemy import text as _text
    import json, re as _re

    # 查缓存
    cached = await db.execute(
        _text("SELECT questions FROM chapter_quizzes WHERE chapter_id = :cid"),
        {"cid": chapter_id}
    )
    row = cached.fetchone()
    if row:
        return {"code": 200, "msg": "success", "data": {"questions": row.questions, "total": len(row.questions), "cached": True}}

    # 查章节关联知识点
    ents = await db.execute(
        _text("""
            SELECT ke.entity_id::text, ke.canonical_name, ke.short_definition
            FROM chapter_entity_links cel
            JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
            WHERE cel.chapter_id = CAST(:cid AS uuid)
              AND ke.review_status = 'approved'
        """),
        {"cid": chapter_id}
    )
    entities = [dict(r._mapping) for r in ents.fetchall()]

    if not entities:
        return {"code": 200, "msg": "success", "data": {"questions": [], "cached": False}}

    # 每个知识点生成1题，全量保存，展示时随机抽取
    count = len(entities)

    # 调用 LLM 生成
    llm = get_llm_gateway()
    entities_json = json.dumps(
        [{"entity_id": e["entity_id"],
          "name": e["canonical_name"],
          "definition": (e.get("short_definition") or "")[:100]}
         for e in entities],
        ensure_ascii=False
    )
    raw = await llm.generate(
        QUIZ_GENERATION_PROMPT.format(count=count, entities_json=entities_json),
        model_route="knowledge_extraction"
    )

    # 解析 JSON
    clean = _re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    match = _re.search(r"\[.*\]", clean, _re.DOTALL)
    questions = []
    if match:
        try:
            questions = json.loads(match.group())
        except Exception:
            questions = []

    # 保存到数据库
    await db.execute(
        _text("""
            INSERT INTO chapter_quizzes (chapter_id, questions, question_count)
            VALUES (:cid, CAST(:q AS jsonb), :cnt)
            ON CONFLICT (chapter_id) DO NOTHING
        """),
        {"cid": chapter_id, "q": json.dumps(questions, ensure_ascii=False), "cnt": len(questions)}
    )
    await db.commit()

    return {"code": 200, "msg": "success", "data": {"questions": questions, "total": len(questions), "cached": False}}


class QuizAnswerItem(BaseModel):
    question_id: str
    entity_id:   str
    type:        str
    is_correct:  bool  # 前端判题（单选/判断），简答题由用户自评


class SubmitQuizRequest(BaseModel):
    chapter_id: str
    answers:    list[QuizAnswerItem]


@learner_router.post("/chapter-quiz/submit")
async def submit_chapter_quiz(
    req:          SubmitQuizRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """提交测验答案，按知识点更新掌握度。"""
    from sqlalchemy import text as _text

    user_id = current_user["user_id"]
    updated = []

    for ans in req.answers:
        # 按题型确定分值
        if ans.type == "true_false":
            delta = 0.1 if ans.is_correct else -0.05
        else:
            delta = 0.2 if ans.is_correct else -0.1

        await db.execute(
            _text("""
                INSERT INTO learner_knowledge_states
                  (user_id, entity_id, mastery_score, last_reviewed_at, review_count)
                VALUES
                  (CAST(:uid AS uuid), CAST(:eid AS uuid),
                   GREATEST(0, LEAST(1, :delta)),
                   now(), 1)
                ON CONFLICT (user_id, entity_id) DO UPDATE SET
                  mastery_score    = GREATEST(0.0, LEAST(1.0,
                                      learner_knowledge_states.mastery_score + :delta)),
                  last_reviewed_at = now(),
                  review_count     = learner_knowledge_states.review_count + 1
            """),
            {"uid": user_id, "eid": ans.entity_id, "delta": delta}
        )
        updated.append({"entity_id": ans.entity_id, "delta": delta, "correct": ans.is_correct})

    correct = sum(1 for a in req.answers if a.is_correct)
    total   = len(req.answers)
    score   = round(correct / total * 100) if total else 0

    # H-6 埋点：记录错题实体
    import json as _json_h6, uuid as _uuid_h6
    wrong_ids = [str(a.entity_id) for a in req.answers
                 if not a.is_correct and getattr(a, "entity_id", None)]
    await db.execute(
        _text("""
            INSERT INTO chapter_quiz_attempts
              (id, user_id, chapter_id, score, correct_count, total_count, wrong_entity_ids)
            VALUES
              (gen_random_uuid(), CAST(:uid AS uuid), :cid,
               :score, :correct, :total, CAST(:wrong AS jsonb))
        """),
        {"uid": user_id, "cid": req.chapter_id, "score": score,
         "correct": correct, "total": total,
         "wrong": _json_h6.dumps(wrong_ids)}
    )
    await db.commit()

    return {
        "code": 200, "msg": "success",
        "data": {
            "score":   score,
            "correct": correct,
            "total":   total,
            "updated": updated,
        }
    }
