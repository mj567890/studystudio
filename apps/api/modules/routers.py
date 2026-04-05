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
    svc = TutorialGenerationService(db)
    # 触发或复用教程生成
    tutorial_id = await svc.generate(topic_key, current_user["user_id"])

    # 返回当前可用的教程内容
    result = await db.execute(
        __import__("sqlalchemy").text("""
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
    return {
        "code": 200, "msg": "success",
        "data": {
            "tutorial_id":  row.tutorial_id,
            "topic_key":    row.topic_key,
            "chapter_tree": row.chapter_tree,
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
