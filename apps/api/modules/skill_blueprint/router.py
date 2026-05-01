from __future__ import annotations
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user
from apps.api.modules.skill_blueprint.schema import (
    GenerateBlueprintRequest, StartGenerationRequest,
    CalibrationQuestionRequest, CalibrationAnswers,
    CourseMapRegenerateRequest, SubmitCalibrationRequest,
)
from apps.api.modules.skill_blueprint.service import BlueprintService

router = APIRouter(prefix="/api/blueprints", tags=["skill_blueprint"])
logger = structlog.get_logger()

@router.get("/{topic_key}")
async def get_blueprint(topic_key: str, db: AsyncSession = Depends(get_db),
                        current_user: dict = Depends(get_current_user),
                        space_id: str | None = None):
    svc = BlueprintService(db)
    bp = await svc.get_blueprint(topic_key, space_id=space_id)
    if not bp:
        raise HTTPException(404, detail={"code": "BP_001",
                                         "msg": f"topic '{topic_key}' 暂无已发布蓝图"})
    if bp.space_id:
        from apps.api.modules.space.service import SpaceService, SpaceError
        try:
            await SpaceService(db).require_space_access(bp.space_id, current_user["user_id"])
        except SpaceError as e:
            raise HTTPException(403, detail={"code": e.code, "msg": e.msg})
    return {"code": 200, "data": bp.model_dump()}

@router.get("/{topic_key}/status")
async def get_blueprint_status(topic_key: str, db: AsyncSession = Depends(get_db),
                                current_user: dict = Depends(get_current_user),
                                space_id: str | None = None):
    svc = BlueprintService(db)
    bp = await svc.get_status(topic_key, space_id=space_id)
    if bp.blueprint_id and bp.space_id:
        from apps.api.modules.space.service import SpaceService, SpaceError
        try:
            await SpaceService(db).require_space_access(bp.space_id, current_user["user_id"])
        except SpaceError as e:
            raise HTTPException(403, detail={"code": e.code, "msg": e.msg})
    return {"code": 200, "data": bp.model_dump()}

@router.post("/{topic_key}/generate")
async def trigger_generate(topic_key: str,
                            req: GenerateBlueprintRequest = GenerateBlueprintRequest(),
                            db: AsyncSession = Depends(get_db),
                            current_user: dict = Depends(get_current_user)):
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository
    repo = BlueprintRepository(db)
    existing = await repo.get_by_topic(topic_key)
    if existing and existing["status"] in ("generating","review","published") and not req.force_regen:
        return {"code": 200, "data": {"message": f"蓝图已存在（{existing['status']}），如需重建传 force_regen=true",
                                       "blueprint_id": existing["blueprint_id"],
                                       "status": existing["status"]}}
    space_id = req.space_id or await repo.resolve_space_id(topic_key)
    try:
        from apps.api.tasks.blueprint_tasks import synthesize_blueprint
        task = synthesize_blueprint.apply_async(
            args=[topic_key, space_id, req.teacher_instruction, req.type_instructions],
            queue="knowledge"
        )
        logger.info("Blueprint generation triggered", topic_key=topic_key, task_id=task.id)
    except Exception as e:
        logger.error("Failed to trigger", error=str(e))
        raise HTTPException(500, detail={"code": "BP_002", "msg": "任务触发失败"})
    return {"code": 200, "data": {"message": "蓝图生成任务已触发，请通过 /status 接口轮询进度",
                                   "topic_key": topic_key}}

@router.post("/{topic_key}/publish")
async def publish_blueprint(topic_key: str, db: AsyncSession = Depends(get_db),
                             current_user: dict = Depends(get_current_user)):
    # 权限检查：支持 roles（数组）和 role（字符串）两种 token 格式
    _roles = current_user.get("roles") or []
    if isinstance(_roles, str):
        _roles = [_roles]
    _role = current_user.get("role", "")
    if _role and _role not in _roles:
        _roles = _roles + [_role]
    if not any(r in ("admin", "superadmin") for r in _roles):
        raise HTTPException(403, detail={"code": "BP_003", "msg": "仅管理员可发布蓝图"})
    repo = BlueprintRepository(db)
    bp_row = await repo.get_by_topic(topic_key)
    space_id = bp_row.get("space_id") if bp_row else None
    svc = BlueprintService(db)
    result = await svc.publish(topic_key, space_id=space_id)
    return {"code": 200 if result.status == "published" else 400,
            "data": result.model_dump()}


# ══════════════════════════════════════════
# 阶段 1+2：课程方案提案 + 启动生成
# ══════════════════════════════════════════

@router.post("/{topic_key}/proposals")
async def generate_proposals(topic_key: str, db: AsyncSession = Depends(get_db),
                              current_user: dict = Depends(get_current_user)):
    """AI 生成 3 套课程设计方案供教师选择。"""
    from apps.api.tasks.blueprint_tasks import generate_course_proposals
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository

    repo = BlueprintRepository(db)
    space_id = await repo.resolve_space_id(topic_key)
    if not space_id:
        raise HTTPException(404, detail={"code": "BP_004", "msg": f"未找到 topic '{topic_key}' 对应的知识空间"})

    # 检查是否已有缓存的方案（5 分钟内不重新生成）
    from sqlalchemy import text
    row = await db.execute(
        text("""SELECT course_proposals::text, proposals_generated_at
                FROM knowledge_spaces WHERE space_id = CAST(:sid AS uuid)"""),
        {"sid": space_id}
    )
    existing = row.fetchone()
    if existing and existing[0] and existing[1]:
        from datetime import datetime, timedelta, timezone
        age = datetime.now(timezone.utc) - existing[1].replace(tzinfo=timezone.utc)
        if age < timedelta(minutes=5):
            import json
            return {"code": 200, "data": {"proposals": json.loads(existing[0]), "cached": True}}

    proposals = await generate_course_proposals(topic_key, space_id)
    return {"code": 200, "data": {"proposals": proposals, "cached": False}}


@router.post("/{topic_key}/start-generation")
async def start_generation(topic_key: str, req: StartGenerationRequest,
                            db: AsyncSession = Depends(get_db),
                            current_user: dict = Depends(get_current_user)):
    """教师选择课程方案 + 填空调整后，保存配置并启动课程生成。"""
    import json
    from apps.api.tasks.blueprint_tasks import synthesize_blueprint
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository
    from sqlalchemy import text as _sg_text

    repo = BlueprintRepository(db)
    space_id = req.space_id

    # 从 knowledge_spaces 读取对应方案
    row = await db.execute(
        _sg_text("""SELECT course_proposals::text FROM knowledge_spaces
                    WHERE space_id = CAST(:sid AS uuid)"""),
        {"sid": space_id}
    )
    existing = row.fetchone()
    if not existing or not existing[0]:
        raise HTTPException(400, detail={"code": "BP_005", "msg": "请先生成课程方案（POST /proposals）"})

    proposals = json.loads(existing[0])
    selected = None
    for p in proposals:
        if p.get("id") == req.selected_proposal_id:
            selected = p
            break
    if not selected:
        raise HTTPException(400, detail={"code": "BP_006",
                                          "msg": f"无效的方案 ID: {req.selected_proposal_id}"})

    # 保存教师选择到 blueprint（创建 draft 记录或更新已有）
    existing_bp = await repo.get_by_topic(topic_key)
    if not existing_bp:
        from apps.api.modules.skill_blueprint.repository import BlueprintRepository as BR
        # 先创建 draft blueprint
        blueprint_id = await repo.create_blueprint(
            topic_key=topic_key,
            title=selected.get("course_structure", {}).get("stage_breakdown", topic_key),
            skill_goal="",
            space_id=space_id,
        )

    # 更新 blueprint 的提案选择字段
    adjustments = req.adjustments or {}
    await db.execute(
        _sg_text("""UPDATE skill_blueprints
                    SET selected_proposal = CAST(:proposal AS jsonb),
                        selected_proposal_id = :pid,
                        proposal_adjustments = CAST(:adj AS jsonb),
                        extra_notes = :notes,
                        status = 'generating'
                    WHERE topic_key = :tk AND space_id = CAST(:sid AS uuid)"""),
        {
            "proposal": json.dumps(selected, ensure_ascii=False),
            "pid": req.selected_proposal_id,
            "adj": json.dumps(adjustments, ensure_ascii=False),
            "notes": req.extra_notes or "",
            "tk": topic_key,
            "sid": space_id,
        }
    )

    # ★ v2.2: 保存经验校准答案 + 计算 confidence_score
    if req.calibration_answers:
        answers = req.calibration_answers
        # 计算 confidence_score
        answered_count = sum(
            1 for v in answers.values()
            if v and v != "不清楚" and v != "skip" and v != []
        )
        total_questions = max(5, len(answers))
        confidence_score = min(1.0, answered_count / total_questions)

        # 构建 experience_calibration JSONB
        calibration_data = {
            "confidence_score": confidence_score,
            "confidence_details": {
                "questions_answered": answered_count,
                "questions_skipped": total_questions - answered_count,
            },
            "real_pain_points": [
                {"label": opt.get("label", ""), "entity_id": opt.get("entity_id", "")}
                for opt in answers.get("q1_pain_points", [])
            ] if isinstance(answers.get("q1_pain_points"), list) else [],
            "selected_cases": [
                {"id": opt.get("id", ""), "label": opt.get("label", ""),
                 "source": "teacher_selected" if not opt.get("let_me_say") else "teacher_provided"}
                for opt in (answers.get("q2_cases", []) if isinstance(answers.get("q2_cases"), list) else [answers.get("q2_cases", {})])
            ] if answers.get("q2_cases") else [],
            "real_misconceptions": [
                {"label": opt.get("label", ""), "entity_id": opt.get("entity_id", "")}
                for opt in answers.get("q3_misconceptions", [])
            ] if isinstance(answers.get("q3_misconceptions"), list) else [],
            "priority_ranking": answers.get("q4_priority", []) if isinstance(answers.get("q4_priority"), list) else [],
            "red_lines": [
                {"label": opt.get("label", ""), "entity_id": opt.get("entity_id", "")}
                for opt in answers.get("q5_red_lines", [])
            ] if isinstance(answers.get("q5_red_lines"), list) else [],
        }

        await db.execute(
            _sg_text("""UPDATE skill_blueprints
                        SET experience_calibration = CAST(:cal AS jsonb),
                            calibration_confidence_score = :score
                        WHERE topic_key = :tk AND space_id = CAST(:sid AS uuid)"""),
            {
                "cal": json.dumps(calibration_data, ensure_ascii=False),
                "score": confidence_score,
                "tk": topic_key,
                "sid": space_id,
            }
        )
        logger.info("[v2.2] Calibration answers saved",
                   answered=answered_count, confidence_score=confidence_score)

    await db.commit()

    # 触发异步生成（保留旧版 teacher_instruction/type_instructions 兼容）
    task = synthesize_blueprint.apply_async(
        args=[topic_key, space_id,
              req.extra_notes,  # teacher_instruction
              None],  # type_instructions — v2 不再使用，改用数据库中的 selected_proposal
        queue="knowledge"
    )
    logger.info("Blueprint generation started via proposal", topic_key=topic_key,
                proposal_id=req.selected_proposal_id, task_id=task.id)

    return {"code": 200, "data": {
        "message": "课程生成任务已启动",
        "topic_key": topic_key,
        "selected_proposal_id": req.selected_proposal_id,
        "task_id": task.id,
        "confidence_score": confidence_score if 'confidence_score' in locals() else None,
    }}


# ══════════════════════════════════════════
# v2.2 新增：经验校准 + Course Map 端点
# ══════════════════════════════════════════

@router.post("/{topic_key}/calibration-questions")
async def get_calibration_questions(topic_key: str, req: CalibrationQuestionRequest,
                                     db: AsyncSession = Depends(get_db),
                                     current_user: dict = Depends(get_current_user)):
    """★v2.2: 生成 5 道经验校准选择题（动态访谈）。"""
    from apps.api.tasks.blueprint_tasks import generate_calibration_questions
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository

    repo = BlueprintRepository(db)
    space_id = req.space_id or await repo.resolve_space_id(topic_key)
    if not space_id:
        raise HTTPException(404, detail={"code": "BP_004",
                                          "msg": f"未找到 topic '{topic_key}' 对应的知识空间"})

    result = await generate_calibration_questions(
        topic_key, space_id,
        selected_proposal_id=req.selected_proposal_id,
        adjustments=req.adjustments,
    )
    return {"code": 200, "data": result}


@router.get("/{topic_key}/course-map")
async def get_course_map(topic_key: str, db: AsyncSession = Depends(get_db),
                         current_user: dict = Depends(get_current_user),
                         space_id: str | None = None):
    """★v2.2: 获取 Course Map 预览（含校准路由分配）。"""
    import json
    from sqlalchemy import text as _cm_text

    if not space_id:
        from apps.api.modules.skill_blueprint.repository import BlueprintRepository
        repo = BlueprintRepository(db)
        space_id = await repo.resolve_space_id(topic_key)
        if not space_id:
            raise HTTPException(404, detail={"code": "BP_004",
                                              "msg": f"未找到 topic '{topic_key}' 对应的知识空间"})

    row = await db.execute(
        _cm_text("""SELECT course_map::text, course_map_validated, course_map_issues::text,
                            calibration_confidence_score
                     FROM skill_blueprints
                     WHERE topic_key = :tk AND space_id = CAST(:sid AS uuid)
                     ORDER BY version DESC LIMIT 1"""),
        {"tk": topic_key, "sid": space_id}
    )
    bp = row.fetchone()
    if not bp or not bp[0]:
        return {"code": 200, "data": {"course_map": None, "message": "Course Map 尚未生成"}}

    return {"code": 200, "data": {
        "course_map": json.loads(bp[0]),
        "validated": bp[1] or False,
        "issues": json.loads(bp[2]) if bp[2] else [],
        "confidence_score": float(bp[3]) if bp[3] is not None else 0.0,
    }}


@router.post("/{topic_key}/course-map/regenerate")
async def regenerate_course_map(topic_key: str, req: CourseMapRegenerateRequest,
                                 db: AsyncSession = Depends(get_db),
                                 current_user: dict = Depends(get_current_user)):
    """★v2.2: 重新规划 Course Map（含反例注入 + 原因选择）。"""
    import json
    from sqlalchemy import text as _rg_text
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository

    repo = BlueprintRepository(db)
    space_id = await repo.resolve_space_id(topic_key)
    if not space_id:
        raise HTTPException(404, detail={"code": "BP_004",
                                          "msg": f"未找到 topic '{topic_key}' 对应的知识空间"})

    # 读取当前 Course Map 作为反例
    row = await db.execute(
        _rg_text("""SELECT course_map::text, experience_calibration::text,
                            extra_notes
                     FROM skill_blueprints
                     WHERE topic_key = :tk AND space_id = CAST(:sid AS uuid)
                     ORDER BY version DESC LIMIT 1"""),
        {"tk": topic_key, "sid": space_id}
    )
    bp = row.fetchone()
    if not bp:
        raise HTTPException(400, detail={"code": "BP_007", "msg": "尚未生成 Course Map"})

    previous_map = json.loads(bp[0]) if bp[0] else None
    experience_calibration = json.loads(bp[1]) if bp[1] else None

    logger.info("[v2.2] Course Map regenerate requested",
               topic_key=topic_key, reason=req.reason)

    return {"code": 200, "data": {
        "message": "重新规划请求已接收，将在前端交互中触发 Course Map 重新生成流程",
        "reason": req.reason,
        "marked_chapters": req.marked_chapters,
    }}


@router.post("/{topic_key}/submit-calibration")
async def submit_calibration(topic_key: str, req: SubmitCalibrationRequest,
                              db: AsyncSession = Depends(get_db),
                              current_user: dict = Depends(get_current_user)):
    """★v2.2: 已有课程补答经验校准，答完可选立即触发全课程重建。"""
    import json
    from sqlalchemy import text as _sc_text
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository

    repo = BlueprintRepository(db)
    space_id = req.space_id

    # 检查 blueprint 是否存在
    existing = await repo.get_by_topic(topic_key)
    if not existing:
        raise HTTPException(404, detail={"code": "BP_001",
                                          "msg": f"topic '{topic_key}' 暂无蓝图"})

    answers = req.answers

    # 计算 confidence_score
    answered_count = sum(
        1 for v in answers.values()
        if v and v != "不清楚" and v != "skip" and v != []
    )
    total_questions = max(5, len(answers))
    confidence_score = min(1.0, answered_count / total_questions)

    # 构建 experience_calibration JSONB（与 start-generation 逻辑一致）
    calibration_data = {
        "confidence_score": confidence_score,
        "confidence_details": {
            "questions_answered": answered_count,
            "questions_skipped": total_questions - answered_count,
            "calibration_source": "retroactive",  # 标记为补答
        },
        "real_pain_points": [
            {"label": opt.get("label", ""), "entity_id": opt.get("entity_id", "")}
            for opt in answers.get("q1_pain_points", [])
        ] if isinstance(answers.get("q1_pain_points"), list) else [],
        "selected_cases": [
            {"id": opt.get("id", ""), "label": opt.get("label", ""),
             "source": "teacher_selected" if not opt.get("let_me_say") else "teacher_provided"}
            for opt in (answers.get("q2_cases", []) if isinstance(answers.get("q2_cases"), list) else [answers.get("q2_cases", {})])
        ] if answers.get("q2_cases") else [],
        "real_misconceptions": [
            {"label": opt.get("label", ""), "entity_id": opt.get("entity_id", "")}
            for opt in answers.get("q3_misconceptions", [])
        ] if isinstance(answers.get("q3_misconceptions"), list) else [],
        "priority_ranking": answers.get("q4_priority", []) if isinstance(answers.get("q4_priority"), list) else [],
        "red_lines": [
            {"label": opt.get("label", ""), "entity_id": opt.get("entity_id", "")}
            for opt in answers.get("q5_red_lines", [])
        ] if isinstance(answers.get("q5_red_lines"), list) else [],
    }

    await db.execute(
        _sc_text("""UPDATE skill_blueprints
                    SET experience_calibration = CAST(:cal AS jsonb),
                        calibration_confidence_score = :score
                    WHERE topic_key = :tk AND space_id = CAST(:sid AS uuid)"""),
        {
            "cal": json.dumps(calibration_data, ensure_ascii=False),
            "score": confidence_score,
            "tk": topic_key,
            "sid": space_id,
        }
    )
    await db.commit()

    logger.info("[v2.2] Retroactive calibration saved",
               topic_key=topic_key, answered=answered_count,
               confidence_score=confidence_score)

    result = {
        "message": "经验校准数据已保存",
        "topic_key": topic_key,
        "confidence_score": confidence_score,
        "questions_answered": answered_count,
    }

    # 如果请求立即重建，触发生成任务
    if req.regenerate:
        from apps.api.tasks.blueprint_tasks import synthesize_blueprint
        extra_notes = existing.get("extra_notes") or ""
        task = synthesize_blueprint.apply_async(
            args=[topic_key, space_id, extra_notes, None],
            queue="knowledge"
        )
        result["regenerate_triggered"] = True
        result["task_id"] = task.id
        logger.info("[v2.2] Regeneration triggered after calibration",
                   topic_key=topic_key, task_id=task.id)

    return {"code": 200, "data": result}
