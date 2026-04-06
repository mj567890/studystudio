"""
apps/api/modules/learner/learner_router.py  (Block C)
apps/api/modules/tutorial/tutorial_router.py (Block D)
apps/api/modules/teaching/teaching_router.py (Block E)

合并在一个文件中，生产时应拆分到各模块目录。
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
    completed:   bool


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
              (user_id, tutorial_id, chapter_id, completed, completed_at)
            VALUES
              (:uid, :tid, :chid, :done, CASE WHEN :done THEN NOW() ELSE NULL END)
            ON CONFLICT (user_id, tutorial_id, chapter_id)
            DO UPDATE SET
              completed    = EXCLUDED.completed,
              completed_at = EXCLUDED.completed_at
        """),
        {
            "uid":  current_user["user_id"],
            "tid":  req.tutorial_id,
            "chid": req.chapter_id,
            "done": req.completed,
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
    topic_key:    str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    from sqlalchemy import text as _text
    svc = TutorialGenerationService(db)
    # 触发或复用教程生成
    tutorial_id = await svc.generate(topic_key, current_user["user_id"])

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
    svc = TeachingChatService(db)
    topic_key = req.context.get("topic_key", "")

    response, diagnosis, profile_version = await svc.chat_and_prepare(
        conversation_id = req.conversation_id,
        user_message    = req.message,
        topic_key       = topic_key,
        user_id         = current_user["user_id"],
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
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """创建新的对话会话。"""
    import uuid
    conv_id = str(uuid.uuid4())
    await db.execute(
        __import__("sqlalchemy").text("""
            INSERT INTO conversations (conversation_id, user_id, topic_key)
            VALUES (:cid, :uid, :tk)
        """),
        {"cid": conv_id, "uid": current_user["user_id"], "tk": topic_key}
    )
    await db.commit()
    return {"code": 201, "msg": "success", "data": {"conversation_id": conv_id}}
