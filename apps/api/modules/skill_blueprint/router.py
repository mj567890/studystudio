from __future__ import annotations
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.core.db import get_db
from apps.api.modules.auth.router import get_current_user
from apps.api.modules.skill_blueprint.schema import GenerateBlueprintRequest
from apps.api.modules.skill_blueprint.service import BlueprintService

router = APIRouter(prefix="/api/blueprints", tags=["skill_blueprint"])
logger = structlog.get_logger()

@router.get("/{topic_key}")
async def get_blueprint(topic_key: str, db: AsyncSession = Depends(get_db),
                        current_user: dict = Depends(get_current_user)):
    svc = BlueprintService(db)
    bp = await svc.get_blueprint(topic_key)
    if not bp:
        raise HTTPException(404, detail={"code": "BP_001",
                                         "msg": f"topic '{topic_key}' 暂无已发布蓝图"})
    return {"code": 200, "data": bp.model_dump()}

@router.get("/{topic_key}/status")
async def get_blueprint_status(topic_key: str, db: AsyncSession = Depends(get_db),
                                current_user: dict = Depends(get_current_user)):
    svc = BlueprintService(db)
    return {"code": 200, "data": (await svc.get_status(topic_key)).model_dump()}

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
        task = synthesize_blueprint.apply_async(args=[topic_key, space_id], queue="knowledge")
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
    svc = BlueprintService(db)
    result = await svc.publish(topic_key)
    return {"code": 200 if result.status == "published" else 400,
            "data": result.model_dump()}
